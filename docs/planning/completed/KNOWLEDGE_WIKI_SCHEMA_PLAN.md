# Plan #9 — Knowledge Wiki Schema v1.0 (Investment Schema Unification)

> Archived 2026-05-04 under `docs/planning/completed/` after shipped status verification.

**Status**: ✅ **SHIPPED 2026-04-25** — all 8 sub-phases (A, B, C, D, E, F, H, I) closed. Sub-phase G cut at R1. AI-excel-addin commits: `cd1b389`, `f167fda`, `6ee2c63`, `ff7a6a3`, `d4e0315`, `f1d05c0`, `9e8ec27`. risk_module commits: `fcc03458`, `daad5e71` + this plan-doc commit. Closes G6 per master plan §6.7.

**Last revised**: 2026-04-25 (SHIPPED — final). Sub-phase H landed `SKILL_CONTRACT_MAP.md` updates (typed methodology retrieval pattern; opt-in consumer skills called out; checklist extended). Sub-phase I landed master plan §6.7 (`MethodologyUnit` + `WikiArticle` contract design) + §12 ship-notes block + `docs/TODO.md` V2.P9d row marked SHIPPED + V2.P9 rollup updated to 7 SHIPPED / 4 DESIGNED.

**Authoritative design reference**: `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.7 (NEW — added by this plan; master plan currently has no §6.7). Master plan §5 G6 + §10b open question #3 + §12 row 9.

**Companion docs**:
- `AI-excel-addin/docs/KNOWLEDGE_LAYER_DESIGN.md` (R7 PASS) — methodology unit shape; frontmatter inert at runtime.
- `AI-excel-addin/docs/KNOWLEDGE_LAYER_WIKI_DESIGN.md` (R3 PASS) — wiki compilation pipeline (DONE).
- `AI-excel-addin/docs/KNOWLEDGE_LAYER_INGESTION_WORKFLOW.md`, `KNOWLEDGE_LAYER_UNIT_TEST_PROTOCOL.md`.
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — skill ↔ methodology ↔ contract cross-layer reference.
- `docs/planning/completed/PROCESS_TEMPLATE_PLAN.md` (plan #5) — `StrategyBias` enum (`value | special_situation | macro | compounder`).
- `docs/planning/completed/EXTENSIBLE_STRATEGY_CATEGORY_PLAN.md` (plan #5b, SHIPPED 2026-04-26) — **coupled plan**. Converts `StrategyBias` to a registry-validated extensible identifier so user-defined categories (`growth`, `income`, `garp`, `event_driven`, etc.) can flow through to `MethodologyUnit.process_template_categories` without code changes. Independent of plan #9 — either can ship first. See §3.1 for the coupling.

**Closes**: **G6** (master plan §5) — *"Knowledge wiki not materialized as data. 'Actionable bites' from the course aren't a queryable, agent-callable schema. Agent access patterns are prose-level (skill files), not typed."*

**Depends on**: Plan #5 ProcessTemplate (SHIPPED 2026-04-23) — uses `StrategyBias` literal as the binding category enum.

---

## 1. Purpose & scope

Plan #9 turns the existing markdown knowledge layer into a **typed, queryable, agent-callable surface** without rewriting the content. The wiki + methodology units are already authored by humans (wiki: 62 articles done; methodology units: 2 of ~20 done, more in progress). Today their YAML frontmatter is inert at runtime (`KNOWLEDGE_LAYER_DESIGN.md` Pass 1 finding #N1, R3 fix). Plan #9 makes that frontmatter validated, queryable, and tied to plan #5 ProcessTemplate categories.

Three deliverables:

1. **`MethodologyUnit v1.0`** + **`WikiArticle v1.0`** — Pydantic source-of-truth shapes mirroring the live frontmatter of `notes/methodology/{phase}/*.md` and `notes/methodology/wiki/{type}/*.md`. Adds two NEW fields to `MethodologyUnit`:
   - `process_template_categories: list[StrategyBias]` — **binding** taxonomy locked to plan #5's `value | special_situation | macro | compounder`.
   - `methodology_tags: list[str]` — **free-form** tag bag for richer concepts (e.g., `spinoff`, `proprietary_data_assets`, `s_curve_inflection`).
2. **Typed retrieval API** — library functions and MCP tools that filter methodology units / wiki articles by category, sia_phase, concept, tag, type. Skills + agents can ask "given strategy=value, which methodology units apply?" without prose path-stitching.
3. **Validation + CI gate** — frontmatter linter. CI fails on schema violations, broken `concepts` cross-references, and tag drift outside the approved tag set. CI warns (does not fail) on broken `case_studies` / `prerequisites` / `related` / `cases` cross-references — see §3.5 severity table for the full split.

### 1.1 Non-goals (v1)

- **No content authoring.** Methodology units and wiki articles continue to be authored by Henry + Claude per the existing KNOWLEDGE_LAYER timeline. Plan #9 ships *infrastructure* for what's already being written.
- **No replacement of `memory_read` / `memory_recall`.** Skills keep using `memory_read("methodology/...")` for raw bodies. Typed retrieval is **supplementary** — for ProcessTemplate-driven surfacing and structured cross-reference. Bodies stay markdown.
- **No DB extraction.** Markdown stays the source of truth on disk. Pydantic schemas validate frontmatter at parse time; indexes are in-memory caches rebuilt from disk.
- **No extension of plan #5's `StrategyBias` enum.** Locked to four values. Plan #9 introduces the `methodology_tags` free-form layer to absorb the broader taxonomy without renegotiating the locked literal.
- **No frontmatter migration of `[[wiki-link]]` references** to typed cross-refs. Wiki cross-links remain Obsidian-rendered human navigation per `KNOWLEDGE_LAYER_WIKI_DESIGN.md` Pass 1 finding #1. Plan #9 only validates that referenced slugs exist (cross-ref existence check), not the link expansion.
- **No tutor / skill prompt rewrites.** Existing `tutor.md`, `tutor-draft.md` `memory_read` literal-path tables keep working. Plan #9 makes typed lookup *available*, doesn't force migration.
- **No frontend UI.** Typed retrieval is library + MCP only.
- **No retroactive backfill of richer fields** (case study tickers, prerequisite slugs) beyond what's already in the frontmatter today.

### 1.2 What this plan adds to the master design

Master plan `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` ships §6.0–§6.6 (six contracts). G6 was deferred per §10b open question #3: *"Knowledge wiki schema (G6): shape of 'actionable bite' + agent retrieval pattern. Out of scope here; follow-on plan."*

Plan #9 writes that "follow-on plan" + adds §6.7 to the master plan describing the two new contracts. Sub-phase I lands the §6.7 patch.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| **A** | `MethodologyUnit` + `WikiArticle` Pydantic contracts | `schema/methodology.py` (new) — both models + nested enums (`SiaPhase`, `WikiArticleType`, `Difficulty`); reuses `_FROZEN_CONTRACT` + `StrategyBias` from existing schema. | ~0.5 day | — |
| B | Frontmatter loader + indexes | `schema/methodology_loader.py` (new) — markdown-frontmatter parser, file → typed object, in-memory `MethodologyIndex` + `WikiIndex` builders. Body stays raw `str`. | ~1 day | A |
| C | Typed retrieval library API | `schema/methodology_lookup.py` (new) — `find_methodology(category=, sia_phase=, concept=, tag=)`, `lookup_wiki(type=, source_module=, slug=)`, `get_methodology(name)`, `get_wiki_article(type, slug)`. Pure functions over A+B. | ~0.5 day | A, B |
| D | MCP tool surface (AI-excel-addin) | `mcp_servers/agents_mcp/methodology_tools.py` (new) — 4 MCP tools wrapping C; gateway-friendly typed errors; agent format. | ~1 day | A, B, C |
| E | Backfill — existing methodology units | Add `process_template_categories` + `methodology_tags` to `business-quality-assessment.md` and `financial-red-flags.md` frontmatter. Update `_template.md` for methodology units (currently no template — write one). | ~0.5 day | A |
| F | Validation + CI gate | `tests/test_methodology_frontmatter.py` (new) — loads every file under `notes/methodology/`, validates against Pydantic, asserts cross-ref slugs per §3.5 severity (concepts + tag-registry + `process_template_categories` = error; `related` + `prerequisites` + `case_studies` + `cases` = warning), asserts tag set ⊂ approved set. CI hooks via existing pytest invocation. | ~0.5 day | A, B, E |
| ~~G~~ | ~~risk_module MCP surface~~ | **CUT in R1** per Codex. AI-excel-addin owns methodology files + memory layer; mirroring tools in risk_module is redundant. Re-introduce only if a concrete risk_module-only caller can't reach the AI-excel-addin gateway — at which point file as a follow-up plan. | — | — |
| H | SKILL_CONTRACT_MAP + skill integration touch points | Update `SKILL_CONTRACT_MAP.md` with `MethodologyUnit` + `WikiArticle` rows. Document the typed lookup pattern. **Skill prompt rewrites NOT included** (non-goal). Specific opt-in consumers called out: `position-initiation`, `/thesis-consultation`, `/thesis-pre-mortem`, `earnings-review` (per Codex R0 finding #8 — methodology informs surfacing, never auto-mutates Thesis). | ~0.5 day | A, B, C, D |
| I | Docs — master plan §6.7 + plan #9 ship notes | Patch `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` to add §6.7 (contract design) + §12 ship marker; update `docs/TODO.md` V2.P9d row from `R0 DRAFT` → `SHIPPED`. | ~0.25 day | A–H |

**Total estimate**: ~4.75 days (sub-phase G cut per R1).

### 2.1 Dependency graph

```
A (Pydantic contracts)
├── B (loader + indexes) ───── C (lookup library) ───── D (AI-excel-addin MCP)
├── E (backfill existing units)
├── F (CI gate) ──────────────── depends on A + B + E
└── H (SKILL_CONTRACT_MAP + skill integration touch points) ── depends on A, B, C, D

I (docs) — last, depends on A–H

(G cut in R1 — see §2 table)
```

---

## 3. Cross-cutting concerns

### 3.1 Two-field categorization design (decision-locked)

The single most consequential design decision in this plan: **how methodology units are tagged for ProcessTemplate-driven surfacing.**

**Decision**: two fields, distinct purposes.

| Field | Type | Validated against | Purpose |
|---|---|---|---|
| `process_template_categories` | `list[StrategyBias]` | Whatever the **current** `StrategyBias` implementation accepts — plan #5b is now SHIPPED, so the live validation surface is the strategy category registry (built-in 4 + user-registered categories via `STRATEGY_CATEGORY_REGISTRY_PATH`). The Pydantic field's *behavior* tracks the alias automatically. | **Binding** — used by typed retrieval API when ProcessTemplate is active. `find_methodology(category="value")` uses this field. |
| `methodology_tags` | `list[str]` | Approved tag set (loaded from `schema/methodology_tag_registry.yaml` — see §3.4) | **Free-form descriptive taxonomy** — captures patterns the wiki already documents (e.g., `spinoff`, `proprietary_data_assets`, `priced_to_perfection`, `s_curve_inflection`, `cyclical_inventory`). Used by `find_methodology(tag=...)` and as cross-ref bridge to `notes/methodology/wiki/patterns/` articles. |

**Why two fields** (vs extending `StrategyBias`):
- Plan #5 shipped `StrategyBias` as a frozen `Literal` across 4 schema files. Plan #5b (`EXTENSIBLE_STRATEGY_CATEGORY_PLAN.md`) has now shipped the coordinated conversion of `StrategyBias` to a registry-validated extensible identifier across every persisted artifact that carries `strategy` (Thesis, InvestmentIdea, ProcessTemplate.investor_profile, HandoffArtifact.thesis.strategy). Plan #9 didn't require a code change: `process_template_categories: list[StrategyBias]` automatically picked up the wider registered set because the type alias `StrategyBias` was preserved (§5b §3.4).
- Even with #5b's extensibility, the two-field design **still holds**: the 4-or-N strategy biases are **portfolio-construction taxonomy** — what kind of investor are you, how do you size positions. Methodology patterns are **content taxonomy** — what kind of analytical lens does this unit apply. They aren't the same axis. Forcing a wiki pattern like `priced_to_perfection` (an anti-pattern lesson) into a strategy bias is a category error regardless of how many biases exist.
- Free-form `methodology_tags` lets the wiki's actual pattern vocabulary surface verbatim. The approved tag registry (§3.4) prevents drift without freezing the taxonomy.

**Both fields can be empty.** A unit with no `process_template_categories` simply doesn't surface in ProcessTemplate-driven retrieval. A unit with no `methodology_tags` doesn't surface in tag retrieval. Empty is normal and fine — most foundational units (e.g., `reading-financial-statements`) apply universally and don't need a strategy tag.

### 3.2 Frontmatter shape — observed today vs. plan v1.0

**Wiki articles** (62 files, all uniform per direct inspection 2026-04-25):
```yaml
---
title: str                              # "Operating Leverage"
type: concept | case | framework | pattern
source_modules: list[int]               # [2], [4, 5]
related: list[str]                      # slugs of any wiki article — concept/case/framework/pattern
                                        # (verified 2026-04-25: live frontmatter crosses types,
                                        # e.g. frameworks/quality-assessment-framework.md cites
                                        # concept slugs; concepts may cite framework slugs)
cases: list[str]                        # MIXED shape per live data (R2 fix):
                                        # — UPPERCASE ticker symbols: [MSCI, PCTY, TWOU]
                                        # — lowercase case-article slugs: [coffee-shop, tradeweb]
                                        # — combined: [PCTY, coffee-shop, tradeweb]  ← real example
                                        # Verified at concepts/financial-models.md, concepts/cost-of-capital.md.
                                        # Resolution: try value as-given (slug match) first;
                                        # if no match AND value matches r"^[A-Z]+$" treat as ticker
                                        # and try `value.lower()` as fallback slug. Both modes warning
                                        # severity in CI per §3.5.
---
```

**Methodology units** (2 files written, uniform per inspection):
```yaml
---
name: str                               # "business-quality-assessment" — must equal filename stem
description: str                        # one-line summary
sia_module: int                         # 1..7
sia_phase: str                          # "fundamental-analysis", etc.
concepts: list[str]                     # wiki concept slugs
tools: list[str]                        # MCP tool names — informational
prerequisites: list[str]                # other methodology unit names
case_studies: list[str]                 # MIXED: UPPERCASE tickers OR lowercase case-article slugs (§3.5)
difficulty: beginner | intermediate | advanced
version: str                            # "1.0"
---
```

**Plan #9 v1.0 adds to `MethodologyUnit`** (both optional, default empty list):
```yaml
process_template_categories: list[StrategyBias]   # NEW — binding to plan #5
methodology_tags: list[str]                       # NEW — free-form taxonomy
```

**Plan #9 v1.0 leaves `WikiArticle` shape unchanged** — wiki is source material, not the primary surfacing layer. ProcessTemplate-driven surfacing happens through methodology units (curated layer); wiki articles surface via slug references from those units. Adding `process_template_categories` to wiki frontmatter would force authors to maintain it on 62+ articles for marginal lookup benefit.

### 3.3 Versioning + backward compatibility

- **`MethodologyUnit v1.0`** is the first typed contract — no v0 to be compatible with. Existing 2 units' frontmatter (`name`, `description`, `sia_module`, etc.) is preserved verbatim; new fields are optional and default to `[]`.
- **`WikiArticle v1.0`** is also first typed contract. The 62 existing files map 1:1 to v1.0 — all 5 fields (`title`, `type`, `source_modules`, `related`, `cases`) are present and valid.
- **`schema_version` field on the Pydantic model** matches plan #5 / plan #6 convention (`schema_version: str = "1.0"` as a class default, not a frontmatter field — frontmatter authors don't write it).

### 3.4 Approved tag registry

`schema/methodology_tag_registry.yaml` ships with sub-phase A, populated by initial scan of:
- All 7 wiki **patterns/** filenames as base tags (e.g., `priced_to_perfection`, `expected_value_decision`)
- Common cross-cutting concepts surfaced in wiki concepts/ (e.g., `recurring_revenue`, `operating_leverage`, `unit_economics`) — these become *both* concept slugs in `concepts:` AND tags in `methodology_tags:` where the unit's *primary lens* is that concept.

Format:
```yaml
# schema/methodology_tag_registry.yaml
version: 1.0
tags:
  # Investment patterns (from wiki/patterns/)
  - attractive_setup
  - expected_value_decision
  - financial_warning_signs
  - ideal_market_characteristics
  - investment_case_types
  - priced_to_perfection
  - return_risk_decomposition
  # Anti-patterns
  - value_trap
  - commodity_cycle
  # Quality lenses
  - high_quality_compounder
  - margin_expansion
  - capital_light
  # Special situations sublabels
  - spinoff
  - ipo_post_lockup
  - restructuring
  - merger_arb
  # Risk lenses
  - factor_risk_dominant
  - idiosyncratic_risk_dominant
  - regulatory_risk
```

Tag additions go through normal PR review. The CI gate (sub-phase F) fails if any methodology unit references a tag not in this registry. Authors add a tag here first, then use it in a unit.

### 3.5 Slug + cross-reference resolution

The frontmatter has multiple cross-reference fields with different resolution semantics. Verified against live data 2026-04-25:

| Field | Where it lives | Format | Resolution target | CI gate |
|---|---|---|---|---|
| `MethodologyUnit.concepts` | unit frontmatter | wiki concept slug | `wiki/concepts/{slug}.md` | **error** if slug doesn't exist |
| `MethodologyUnit.case_studies` | unit frontmatter | UPPERCASE ticker OR lowercase case-article slug (mixed) | `wiki/cases/{slug or ticker.lower()}.md` (may be absent) | **warning** if no case article (case articles lag unit authoring) |
| `MethodologyUnit.prerequisites` | unit frontmatter | other unit name | `notes/methodology/{any-phase}/{name}.md` | **warning** if missing (R1: was error). Reason: only 2 of ~20 units exist as of 2026-04-25; `business-quality-assessment.md` already cites `reading-financial-statements` as a prerequisite that hasn't been authored yet. Promoting to error blocks ship. CI logs missing prerequisites for human review without failing. Re-tighten to error in a follow-up plan once the unit set is complete. |
| `MethodologyUnit.tools` | unit frontmatter | MCP tool name | live MCP tool registry | informational only (R0 decision held) |
| `WikiArticle.related` | wiki frontmatter | **any wiki slug** (concept, case, framework, or pattern) | `wiki/{any_subdir}/{slug}.md` | **warning** if slug doesn't exist anywhere in the wiki tree (R2 fix: was error in R1). Reason: live data has 2 known-missing slugs — `concepts/scalability.md → gross-margin` and `frameworks/decision-making-system.md → price-scenarios` (verified by full-tree scan 2026-04-25; neither `gross-margin.md` nor `price-scenarios.md` exists in the wiki). Promoting to error blocks ship. CI logs missing related slugs for author follow-up; re-tighten to error in a follow-up plan once the wiki gaps are filled. |
| `WikiArticle.cases` | wiki frontmatter | MIXED — UPPERCASE ticker OR lowercase case-article slug | resolution per §4.2 (try value-as-slug first; fall back to `value.lower()` if value matches `^[A-Z]+$`) | **warning** if no case article |

**Loader behavior** (sub-phase B):
- All cross-refs are returned as bare strings on the typed object. The loader does not auto-expand them.
- Cross-ref expansion is the caller's job: `find_methodology(name="business-quality-assessment").concepts → ["recurring-revenue", ...]`, then caller does `lookup_wiki(article_type="concept", slug="recurring-revenue")`.
- **Wiki cross-type resolution** (R1 fix): `lookup_wiki_by_slug(slug)` searches all 4 type directories. `WikiArticle.related` resolves through this since live data crosses types (verified — full scan found 194 cross-type links across concepts/cases/frameworks/patterns).
- **Mixed `cases` resolution** (R2 fix per Codex R1 finding #1): the loader's `_resolve_case_reference(value)` tries `wiki/cases/{value}.md` first (slug-as-given). If that fails AND `value` matches `^[A-Z]+$`, it tries `wiki/cases/{value.lower()}.md` (treat as ticker). Either match resolves; neither match emits a warning. This handles the live mixed shape: `[PCTY, coffee-shop, tradeweb]` resolves three different ways. Note: ticker-to-slug is still best-effort (`PCTY` won't auto-resolve to `paylocity.md`); future plan can add an explicit ticker-alias map if needed.

### 3.6 Indexing performance

The 62 wiki articles + ~20 methodology units (target) are tiny — full disk scan + parse takes <100ms in tests. No persistence, no cache invalidation. Index rebuilds on every process start; runtime cost trivial.

If the wiki grows to 500+ articles per `KNOWLEDGE_LAYER_WIKI_DESIGN.md` Phase 4 (full SIA compilation), revisit caching. Out of scope for v1.

### 3.7 Skill prompt integration — pattern, not migration

Skills today reference methodology via literal `memory_read("methodology/fundamental-analysis/{name}.md")` (e.g., `tutor.md:55`, `tutor-draft.md:58`). Plan #9 does NOT migrate these. Sub-phase H documents a new pattern in `SKILL_CONTRACT_MAP.md`:

> When a skill needs to surface methodology dynamically based on the active ProcessTemplate, prefer `find_methodology(category=template.investor_profile.strategy_bias)` over hardcoded `memory_read` paths. When a skill needs a specific known unit, `memory_read` is still correct and faster.

The pattern is opt-in; existing skills don't need to change. The few new flows that need ProcessTemplate-driven surfacing (e.g., template-aware research start per `SKILL_CONTRACT_MAP.md` Pattern 0.5) become the first consumers.

---

## 4. Sub-phase A — `MethodologyUnit` + `WikiArticle` Pydantic contracts

### 4.1 Goal

Ship the typed contracts in `AI-excel-addin/schema/methodology.py`. Importable, stable, documented; nothing that consumes them yet (that's B–H).

### 4.2 Design

```python
# schema/methodology.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .process_template import StrategyBias  # reuse plan #5 literal

_FROZEN_CONTRACT = ConfigDict(
    extra="forbid",
    str_strip_whitespace=True,
    populate_by_name=True,
    frozen=True,
)

SiaPhase = Literal[
    "foundation",
    "fundamental-analysis",
    "strategic-evaluation",
    "decision-making",
    "risk-management",
    "valuation-modeling",
    "pitch",
]

WikiArticleType = Literal["concept", "case", "framework", "pattern"]
Difficulty = Literal["beginner", "intermediate", "advanced"]


class WikiArticle(BaseModel):
    title: str = Field(min_length=1)
    type: WikiArticleType
    source_modules: list[int] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)        # any wiki slug (concept/case/framework/pattern)
    cases: list[str] = Field(default_factory=list)          # MIXED — UPPERCASE tickers OR lowercase case-article slugs (R2; §3.5)

    # Computed at load time, not in frontmatter:
    slug: str = Field(min_length=1)            # filename stem
    body_md: str = Field(default="")            # raw markdown body

    @field_validator("source_modules")
    @classmethod
    def _validate_modules(cls, value: list[int]) -> list[int]:
        for m in value:
            if not 1 <= m <= 7:
                raise ValueError(f"source_module must be in 1..7; got {m}")
        return value

    schema_version: str = Field(default="1.0")
    model_config = _FROZEN_CONTRACT


class MethodologyUnit(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")
    # NOTE: the regex above accepts a trailing dash (e.g. "abc-" matches).
    # The intent — kebab-case slug matching filename stem — is fully captured by
    # regex + a supplementary `field_validator` rejecting trailing-dash names.
    # See `_validate_name` below. Tightening the regex itself to disallow
    # trailing dashes (e.g. `^[a-z]([a-z0-9-]*[a-z0-9])?$`) is harder to read;
    # the validator is more legible and gives a clearer error message.
    description: str = Field(min_length=1)
    sia_module: int = Field(ge=1, le=7)
    sia_phase: SiaPhase
    concepts: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    case_studies: list[str] = Field(default_factory=list)
    difficulty: Difficulty
    version: str = Field(min_length=1)

    # NEW v1.0
    process_template_categories: list[StrategyBias] = Field(default_factory=list)
    methodology_tags: list[str] = Field(default_factory=list)

    # Computed at load time:
    body_md: str = Field(default="")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        # Reject trailing dashes — the regex above can't express this cleanly.
        # Filename-stem cross-check happens in the loader (sub-phase B), not
        # here; the loader has access to the path, this validator does not.
        if value.endswith("-"):
            raise ValueError("name must not end with '-'")
        return value

    schema_version: str = Field(default="1.0")
    model_config = _FROZEN_CONTRACT
```

### 4.3 Files to create / modify

- `AI-excel-addin/schema/methodology.py` (new, ~120 lines)
- `AI-excel-addin/schema/methodology_tag_registry.yaml` (new, ~40 lines per §3.4 starter list)
- `AI-excel-addin/schema/__init__.py` — export `MethodologyUnit`, `WikiArticle`, `SiaPhase`, `WikiArticleType`, `Difficulty`.

### 4.4 Tests

- `AI-excel-addin/tests/schema/test_methodology.py` (new):
  - Happy path: construct `MethodologyUnit` from valid dict; all fields normalize.
  - `name` regex: rejects uppercase, spaces, leading digits, trailing dashes.
  - `sia_module` bounds: rejects 0 and 8.
  - `process_template_categories`: rejects strings the current `StrategyBias` implementation rejects (plan #5b shipped registry validation: anything not in the registry). Accepts empty list. Concrete test asserts rejection of a clearly-bogus string like `"not_a_real_category"` rather than `"growth"` (since `"growth"` validity is environment-dependent).
  - `methodology_tags`: rejects non-list; accepts empty list. Tag-set validation lives in sub-phase F (CI gate), not in the Pydantic model — keeps the contract pure schema.
  - `WikiArticle.type` rejects strings outside the 4-literal.
  - `WikiArticle.source_modules` rejects 0 and 8.
  - JSON round-trip stability.
  - Frozen-model: `setattr` after construction raises.

---

## 5. Sub-phase B — Frontmatter loader + indexes

### 5.1 Goal

Convert markdown files on disk into typed `MethodologyUnit` / `WikiArticle` instances. Build in-memory indexes. Pure read-side; no mutation.

### 5.2 Design

```python
# schema/methodology_loader.py
from pathlib import Path
import yaml
from .methodology import MethodologyUnit, WikiArticle


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter_dict, body_md)."""
    if not text.startswith("---\n"):
        raise ValueError("file missing YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter not terminated")
    return yaml.safe_load(parts[1]), parts[2]


def load_methodology_unit(path: Path) -> MethodologyUnit:
    text = path.read_text()
    fm, body = parse_frontmatter(text)
    # Inject computed fields:
    fm["body_md"] = body
    unit = MethodologyUnit(**fm)
    # Cross-check filename stem:
    if unit.name != path.stem:
        raise ValueError(f"name {unit.name!r} != filename stem {path.stem!r}")
    return unit


def load_wiki_article(path: Path) -> WikiArticle:
    text = path.read_text()
    fm, body = parse_frontmatter(text)
    fm["body_md"] = body
    fm["slug"] = path.stem
    return WikiArticle(**fm)


class MethodologyIndex:
    """Index of MethodologyUnit objects keyed by name."""
    def __init__(self, root: Path):
        self._by_name: dict[str, MethodologyUnit] = {}
        self._by_phase: dict[str, list[str]] = {}
        self._by_category: dict[str, list[str]] = {}
        self._by_concept: dict[str, list[str]] = {}
        self._by_tag: dict[str, list[str]] = {}
        self.load(root)

    # R2 — explicit legacy-file exclusion (Codex R1 finding Medium #4).
    # These three top-level files are not homogeneous MethodologyUnits per §13.1 #12:
    LEGACY_EXCLUDE = frozenset({"investment_process", "black_book", "software_valuation"})

    def load(self, root: Path) -> None:
        # Walk root for any *.md
        for path in root.rglob("*.md"):
            # Skip wiki articles (handled by WikiIndex)
            if "wiki" in path.parts:
                continue
            # Skip _-prefixed meta-files (_template.md, etc.)
            if path.stem.startswith("_"):
                continue
            # R2 — Skip top-level legacy files explicitly (locked decision §13.1 #12)
            if path.parent == root and path.stem in self.LEGACY_EXCLUDE:
                continue
            try:
                unit = load_methodology_unit(path)
            except ValueError as e:
                # Loader error surfaces with file context for CI gate diagnostics
                raise ValueError(f"{path}: {e}") from e
            self._by_name[unit.name] = unit
            self._by_phase.setdefault(unit.sia_phase, []).append(unit.name)
            for cat in unit.process_template_categories:
                self._by_category.setdefault(cat, []).append(unit.name)
            for concept in unit.concepts:
                self._by_concept.setdefault(concept, []).append(unit.name)
            for tag in unit.methodology_tags:
                self._by_tag.setdefault(tag, []).append(unit.name)

    def get(self, name: str) -> MethodologyUnit | None: ...
    def names(self) -> list[str]: ...


class WikiIndex:
    """Index of WikiArticle objects keyed by (type, slug)."""
    # Same shape, keyed by (type, slug); secondary by source_module
    ...
```

**Loader policy decisions**:
- Files prefixed with `_` (e.g., `_template.md`, `_index.md`, `_playbook.md`, `_manifest.md`) are skipped — they're meta-files, not content.
- Files under `notes/methodology/wiki/` are loaded as `WikiArticle`. Files under `notes/methodology/{any other dir}/` are loaded as `MethodologyUnit`.
- Files at `notes/methodology/*.md` (not in subdir) — `investment_process.md`, `black_book.md`, `software_valuation.md` — are SKIPPED by the methodology loader per locked decision §13.1 #12 (R1). They predate the typed schema and remain prose-only per `KNOWLEDGE_LAYER_DESIGN.md` "Existing Methodology Files" section. Loader implementation uses the explicit `LEGACY_EXCLUDE` frozenset (§5.2). Future migration is a separate plan, not a plan #9 concern.
- Loader errors surface with file path context. Strict-mode (CI gate) raises; lenient-mode (runtime) skips bad files with a logged warning, so a single bad frontmatter file doesn't break the agent.

### 5.3 Files to create / modify

- `AI-excel-addin/schema/methodology_loader.py` (new, ~150 lines)
- `AI-excel-addin/api/memory/__init__.py` — expose `get_methodology_root() -> Path` returning `get_legacy_workspace_dir() / "notes/methodology"`. **R1 correction**: methodology is curated read-only content per `CURATED_READ_PREFIXES = (Path("methodology"),)` at `api/memory/__init__.py:25`. `_seed_workspace_assets()` does NOT seed `notes/methodology` into per-user workspaces, and `memory_read("methodology/...")` already routes curated reads through `get_legacy_workspace_dir()`. Methodology indexes therefore attach to the legacy workspace path, not the per-user `MemoryStoreFactory` path. There is one global index instance per process — not per-user, since the underlying content is shared.

### 5.4 Index lifecycle (R1 expansion)

- **Construction**: `MethodologyIndex` and `WikiIndex` instantiated once at process boot, lazily on first call to `get_methodology_index()` / `get_wiki_index()`. Loaded from `get_methodology_root()`.
- **Rebuild hook**: `rebuild_methodology_indexes()` (admin/test-only entrypoint) — clears and reloads. Used by tests + future admin tooling. Not exposed as MCP tool in v1.
- **No watcher**: file changes during a process lifetime are not picked up. Reasoning: methodology authoring is editorial, low-frequency; users restart the process when shipping new units. Watcher complexity not justified for v1.
- **Lenient runtime**: per §9.4 — bad frontmatter logs and skips at runtime; CI gate is the strict surface.

### 5.5 Tests

- `tests/schema/test_methodology_loader.py`:
  - Parse known-good frontmatter from `business-quality-assessment.md` → assert all fields normalize.
  - Parse `wiki/concepts/recurring-revenue.md` → assert `WikiArticle` shape.
  - Reject file with missing `---` delimiter.
  - Reject file where `name` ≠ filename stem.
  - Index build: load entire `notes/methodology/` tree from a fixture workspace; assert counts (62 wiki articles, 2 methodology units as of 2026-04-25 — fixture should isolate from author-velocity drift).
  - Lookup by phase, by category, by concept, by tag.

---

## 6. Sub-phase C — Typed retrieval library API

### 6.1 Goal

Pure-function lookup wrapping the indexes. No I/O at call time (indexes pre-loaded).

### 6.2 Design

```python
# schema/methodology_lookup.py
from .methodology import MethodologyUnit, WikiArticle, SiaPhase, WikiArticleType
from .methodology_loader import MethodologyIndex, WikiIndex
from .process_template import StrategyBias


def find_methodology(
    *,
    index: MethodologyIndex,
    category: StrategyBias | None = None,
    sia_phase: SiaPhase | None = None,
    concept: str | None = None,
    tag: str | None = None,
) -> list[MethodologyUnit]:
    """AND of all provided filters. None = no constraint on that axis.

    Returns units in deterministic order (by name asc).
    Empty filter set returns all units.
    """
    ...


def get_methodology(*, index: MethodologyIndex, name: str) -> MethodologyUnit | None: ...


def lookup_wiki(
    *,
    index: WikiIndex,
    article_type: WikiArticleType | None = None,
    source_module: int | None = None,
    slug: str | None = None,
) -> list[WikiArticle]: ...


def get_wiki_article(*, index: WikiIndex, type: WikiArticleType, slug: str) -> WikiArticle | None: ...
```

### 6.3 Files to create / modify

- `AI-excel-addin/schema/methodology_lookup.py` (new, ~60 lines)

### 6.4 Tests

- `tests/schema/test_methodology_lookup.py`:
  - `find_methodology(category="value")` returns only units where `"value" in process_template_categories`.
  - AND semantics: `find_methodology(category="value", sia_phase="fundamental-analysis")` filters both.
  - Empty filter returns all.
  - Deterministic ordering.
  - `lookup_wiki(article_type="pattern")` returns 7 items (matches `wiki/patterns/` count).

---

## 7. Sub-phase D — MCP tool surface (AI-excel-addin)

### 7.1 Goal

Expose the lookup library as MCP tools so agents (gateway-side) can call them. AI-excel-addin owns these because it owns the methodology files.

### 7.2 Tool surface

Four tools, all read-only:

| Tool | Args | Returns |
|---|---|---|
| `find_methodology_units` | `category?`, `sia_phase?`, `concept?`, `tag?` (all optional strings, validated against literals where applicable) | List of `{name, description, sia_phase, sia_module, difficulty, process_template_categories, methodology_tags}` — minus body. Body retrieved separately via `memory_read` or `get_methodology_unit`. |
| `get_methodology_unit` | `name` (required) | Full unit including `body_md`. |
| `lookup_wiki_articles` | `article_type?`, `source_module?`, `slug?` | List of `{slug, title, type, source_modules}` — minus body. |
| `get_wiki_article` | `type`, `slug` (both required) | Full article including `body_md`. |

**Why list endpoints exclude body**: catalog-style queries don't need to ship 5–10K tokens of markdown per result. Body retrieval is one extra round-trip when the agent has decided which unit to read.

**Agent format**: each tool returns `{snapshot: {...}, flags: [...]}` per `format="agent"` convention. Flags surface things like "no methodology units match these filters" or "tag X is in registry but no units use it yet."

### 7.3 Typed errors

```python
class MethodologyNotFoundError(LookupError): ...
class WikiArticleNotFoundError(LookupError): ...
class MethodologyTagUnknownError(ValueError):
    """Tag not in approved registry. Surface in MCP for agent diagnostics."""
```

Mapped through gateway error classifier so callers get structured errors, not 500s.

### 7.4 Files to create / modify

- `AI-excel-addin/mcp_servers/agents_mcp/methodology_tools.py` (new, ~200 lines)
- `AI-excel-addin/mcp_servers/agents_mcp/server.py` — register the 4 new tools.
- Gateway error classifier — extend with the 3 new typed-error classes.

### 7.5 Tests

- `tests/mcp/test_methodology_tools.py`:
  - Each tool: golden path + empty result + each typed error.
  - Snapshot/flags shape.
  - Filter-arg validation: `category="not_a_real_category"` returns a typed error (clearly-bogus value chosen rather than `"growth"` since the latter's validity is environment-dependent post-#5b).

---

## 8. Sub-phase E — Backfill existing methodology units

### 8.1 Goal

Add `process_template_categories` + `methodology_tags` to the 2 already-written units so the typed retrieval has actual content to serve from day 1. Write the methodology unit `_template.md` so future authors get the right shape.

### 8.2 Concrete edits

**`fundamental-analysis/business-quality-assessment.md`** — add to frontmatter:
```yaml
process_template_categories: [compounder, value]
methodology_tags: [high_quality_compounder, margin_expansion, capital_light]
```
Reasoning: the 5-pillar quality framework is the bread-and-butter compounder lens; value investors also use it (a "good business at a fair price" needs the same quality assessment as "great business at a great price"). Tags reflect the unit's primary lenses.

**`fundamental-analysis/financial-red-flags.md`** — add to frontmatter:
```yaml
process_template_categories: [value, compounder, special_situation]
methodology_tags: [financial_warning_signs, value_trap]
```
Reasoning: red flags apply broadly. Tags map to existing wiki pattern files (`patterns/financial-warning-signs.md`, `patterns/value-trap.md` does not exist in current wiki — re-check during implementation; if missing, drop `value_trap` from tags).

**Macro categorization is empty for both** — these units don't apply to a macro thesis.

**Write `notes/methodology/_template.md`** for future units (matches `wiki/_template.md` convention):

```yaml
---
name: unit-slug                              # required, matches filename stem
description: One-line summary.
sia_module: 2                                # 1-7
sia_phase: fundamental-analysis              # see SiaPhase literal
concepts: []                                 # wiki concept slugs
tools: []                                    # MCP tool names
prerequisites: []                            # other unit names
case_studies: []                             # UPPERCASE tickers OR case-article slugs (mixed; §3.5)
difficulty: intermediate                     # beginner | intermediate | advanced
version: 1.0
process_template_categories: []              # NEW — value | special_situation | macro | compounder
methodology_tags: []                         # NEW — see methodology_tag_registry.yaml
---
```

### 8.3 Files to create / modify

- `AI-excel-addin/api/memory/workspace/notes/methodology/fundamental-analysis/business-quality-assessment.md` — frontmatter only.
- `AI-excel-addin/api/memory/workspace/notes/methodology/fundamental-analysis/financial-red-flags.md` — frontmatter only.
- `AI-excel-addin/api/memory/workspace/notes/methodology/_template.md` (new).

### 8.4 Verification

- Sub-phase F's CI gate runs against the backfilled files and passes.
- Run `find_methodology(category="compounder")` from a Python REPL and observe both units in the result.

---

## 9. Sub-phase F — Validation + CI gate

### 9.1 Goal

Prevent frontmatter drift from re-introducing the inert-frontmatter problem. CI gate fails if any methodology unit / wiki article fails Pydantic validation, has a broken cross-ref, or uses an unapproved tag.

### 9.2 Design

**R2 — aligned with §3.5 severity table** (Codex R1 finding High #2 + High #3). Earlier draft promoted some warnings to errors and contradicted §3.5; R2 makes §3.5 the single source of truth.

A pytest test that walks `notes/methodology/` and asserts:

**Errors (CI failure)**:
1. Every `notes/methodology/{phase}/*.md` (excluding files starting with `_` AND the explicit legacy-exclusion list — see §5.2) loads as a valid `MethodologyUnit`.
2. Every `notes/methodology/wiki/{type}/*.md` loads as a valid `WikiArticle`.
3. Every `MethodologyUnit.concepts` slug exists as `wiki/concepts/{slug}.md`.
4. Every `MethodologyUnit.methodology_tags` value exists in `schema/methodology_tag_registry.yaml`.
5. Every `MethodologyUnit.process_template_categories` value validates against the current `StrategyBias` implementation.
6. Top-level legacy methodology files (`investment_process.md`, `black_book.md`, `software_valuation.md`) are explicitly skipped — assert that none of them was attempted as a `MethodologyUnit` parse (regression guard for the §5.2 exclusion).

**Warnings (CI logs but does not fail)**:
7. `MethodologyUnit.prerequisites` slug missing — full unit set not yet authored (§3.5).
8. `MethodologyUnit.case_studies` ticker/slug doesn't resolve via §3.5 mixed-resolution.
9. `WikiArticle.related` slug doesn't exist anywhere in the wiki tree — 2 known gaps today (`gross-margin`, `price-scenarios`); future plan tightens once authored (§3.5).
10. `WikiArticle.cases` ticker/slug doesn't resolve.

Test runs on every CI build via existing pytest invocation. Warning output goes to test logs for human review.

### 9.3 Files to create / modify

- `AI-excel-addin/tests/test_methodology_frontmatter.py` (new, ~150 lines)

### 9.4 Decisions

- **Strict-mode in CI; lenient at runtime.** Production readers (lookup library) skip bad files with a logged warning; CI fails. Avoids the "one bad frontmatter file breaks the agent in prod" footgun.
- **No auto-fix.** Authors fix frontmatter manually based on the CI failure message.

---

## 10. Sub-phase G — CUT in R1

**Status**: cut per Codex R0 finding #5. Removed from §2 sub-phase summary, §2.1 dep graph, §16 test count, §17 acceptance gates.

**Reasoning**: AI-excel-addin owns the methodology files + memory layer (`get_legacy_workspace_dir()`, `MemoryStoreFactory`, `_seed_workspace_assets`). Sub-phase D's MCP tools at `mcp_servers/agents_mcp/methodology_tools.py` are the owner-aligned surface. The agent layer reaches them via the existing gateway — no risk_module-side mirror needed.

**Re-introduction trigger**: file as a follow-up plan only if a concrete risk_module-only caller (e.g. a future editorial-pipeline server-side renderer that runs in the risk_module process and can't reach AI-excel-addin's gateway) emerges. Until then, drop.

---

## 11. Sub-phase H — `SKILL_CONTRACT_MAP.md` updates + integration patterns

### 11.1 Goal

Document the new typed-retrieval pattern so future skill authors discover it. Don't migrate existing skills.

### 11.2 Concrete edits

`AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`:

1. Update the four-layer ASCII diagram to mark layer 1 (wiki) and layer 2 (methodology units) as **typed at frontmatter level** as of plan #9.
2. New section: **"Typed methodology retrieval"** — describes the lookup library + MCP tools, when to prefer over `memory_read`.
3. New row in "Skill → Methodology → Contract mapping" table for any skill that should adopt the typed pattern (initially: `/thesis-consultation`, `/thesis-pre-mortem` — both already cite multiple methodology units).
4. Update "Checklist: adding a new methodology unit" to include:
   - Add `process_template_categories: list[StrategyBias]` (can be empty)
   - Add `methodology_tags: list[str]` (must be subset of `methodology_tag_registry.yaml`)
   - Run `pytest tests/test_methodology_frontmatter.py` locally before committing.
5. Add reference to plan #9 in the doc's "Cross-repo references" section.

### 11.3 Files to create / modify

- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (existing — surgical edits per Edit tool, not full rewrite per memory rule).

---

## 12. Sub-phase I — Master plan §6.7 + ship docs

### 12.1 Master plan §6.7 — new section

Insert into `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` after §6.6 (`Thesis + ThesisLink + ThesisScorecard`):

```markdown
### 6.7 `MethodologyUnit` + `WikiArticle` (new) — closes G6

**Producer**: human authors (Henry + Claude) writing markdown files under `AI-excel-addin/api/memory/workspace/notes/methodology/`.
**Consumer**: agents + skills via `find_methodology` / `lookup_wiki` typed lookup; raw `memory_read` for full-body access.

[Full design content from this plan's §3 + §4 — sub-phase I patches it in.]
```

### 12.2 Other docs

- `docs/TODO.md` row V2.P9d — update from `UNBLOCKED BY PLAN #5 2026-04-23` to `SHIPPED YYYY-MM-DD`.
- Master plan §12 — mark plan #9 SHIPPED with commit refs.

### 12.3 Files to create / modify

- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — surgical edit to add §6.7 + mark §12 row 9 shipped.
- `docs/TODO.md` — V2.P9d row update.

---

## 13. Decisions

### 13.1 Locked

1. **Two-field categorization** (§3.1). `process_template_categories` tracks `StrategyBias` (plan #5b shipped registry validation); `methodology_tags` is free-form via approved registry.
2. **No `StrategyBias` extension in plan #9.** Extensibility is plan #5b's scope; plan #9 consumes whatever shape `StrategyBias` has.
3. **`MethodologyUnit` v1.0 is additive only** to existing frontmatter — `process_template_categories` and `methodology_tags` default to empty list.
4. **`WikiArticle` v1.0 frontmatter unchanged** from current `_template.md`.
5. **Markdown stays source of truth.** No DB extraction, no JSON exports, no parallel storage.
6. **`memory_read` / `memory_recall` not replaced.** Typed lookup is supplementary.
7. **Strict CI / lenient runtime.** Bad frontmatter fails CI; runtime logs and skips.
8. **R1 — Methodology root** (§5.3): indexes load from `get_legacy_workspace_dir() / "notes/methodology"`, NOT per-user `MemoryStoreFactory` paths. Methodology is curated read-only content per `CURATED_READ_PREFIXES`.
9. **R2 — `WikiArticle.related` accepts any wiki slug** (concept/case/framework/pattern) per live data; CI gate resolves cross-type and emits **warning** (not error) on missing slugs because 2 known gaps exist today (`gross-margin`, `price-scenarios`). Re-tighten to error in follow-up once authored.
10. **R1 — `MethodologyUnit.prerequisites` existence check is a warning, not error.** Reason: 2 of ~20 units exist; existing units cite unauthored prerequisites (e.g. `reading-financial-statements`). Promoting to error blocks ship. Re-tighten in a follow-up plan when full unit set lands.
11. **R2 — `WikiArticle.cases` and `MethodologyUnit.case_studies` accept MIXED shape** — UPPERCASE tickers AND lowercase case-article slugs (verified live: `concepts/financial-models.md` has `[PCTY, coffee-shop, tradeweb]`). Resolution per §3.5: try slug-as-given first; fall back to `value.lower()` only if `value` matches `^[A-Z]+$`. Both warning severity. Future plan can add explicit ticker-alias map.
12. **R1 — Top-level legacy methodology files** (`investment_process.md`, `black_book.md`, `software_valuation.md`): permanently excluded from typed loading per Codex R0 finding #4. They are not homogeneous `MethodologyUnit`s — `investment_process.md` is framework-shaped while `black_book.md` and `software_valuation.md` are legacy prose/reference assets. Documented as explicit exclusion list in the loader. Future migration is a separate plan, not a plan #9 blocker.
13. **R1 — Methodology DOES NOT auto-prepopulate `qualitative_factors` from unit bodies** (per Codex R0 finding #8). `ProcessTemplate.seed_qualitative_factors` is the existing seed surface and stays canonical. Methodology-driven surfacing happens via skill-side `find_methodology(...)` lookups (opt-in consumers), never by parsing prose into structured fields.

### 13.2 Open for Codex re-review (R1)

1. **Methodology unit `tools:` field** — currently a list of bare MCP tool names. Should it be validated against the live MCP tool registry, or stay informational? R0/R1 keeps informational; CI gate could later add tool-name existence check.
2. **Tag registry placement** — `schema/methodology_tag_registry.yaml` (proposed) vs. `notes/methodology/_tag_registry.md` (closer to content). R1 prefers `schema/` because the registry is a *contract* enforced by Pydantic-side validation, not content.
3. **`schema_version` strategy** — R1 has it as a class-level default (`"1.0"`), not in frontmatter. Confirm vs. ProcessTemplate / Thesis convention.
4. **Wiki cross-type `related` resolution performance** — at the 500-article horizon (`KNOWLEDGE_LAYER_WIKI_DESIGN.md` Phase 4), is per-article cross-type slug check (4 directories scanned) still cheap enough at index-build time? R1 says yes for current 62 articles; flag for revisit at 200+ articles.

---

## 14. Out of scope (v1) — explicit non-goals recap

| Non-goal | Why | Future plan? |
|---|---|---|
| Authoring more methodology units | Existing KNOWLEDGE_LAYER timeline owns this | Ongoing — not a plan |
| Wiki article → methodology unit auto-distillation | Manual curation per `KNOWLEDGE_LAYER_WIKI_DESIGN.md` Stage 2 | Maybe — author-velocity dependent |
| Frontend UI for methodology browsing | No user surface in v1 | Plan #10 (editorial pipeline) may consume |
| Field-notes auto-promotion to canonical articles | `KNOWLEDGE_LAYER_WIKI_DESIGN.md` "Health Checks" | Operational follow-up |
| Wiki link expansion (`[[wiki-link]]` → typed cross-ref) | Wiki links are Obsidian sugar per design | No — explicit by design |
| Migration of existing skill prompts to `find_methodology` | Pattern-only adoption | Per-skill follow-ups as needed |
| Tutor-mode runtime separation | `KNOWLEDGE_LAYER_DESIGN.md` says prompt-based, locked | No |
| FTS / semantic search of methodology bodies | `memory_recall` already does this | No |
| `MethodologyUnit` body parsing into structured sections (Core Framework / Execute / Guide) | Adds parser complexity for marginal lookup value; sections are markdown headings — readable as-is | Maybe v2 if a strong consumer emerges |
| Versioning + history of methodology unit edits | Markdown + git already provides | No |

---

## 15. Plan #9 fits in the Investment Schema Unification series

| Plan | Status | Closes | Consumes from #9 |
|---|---|---|---|
| #1 Thesis | SHIPPED | G13 | — |
| #2 HandoffArtifact v1.1 | SHIPPED | G5/G9/G11/G13/G14/G15 | — |
| #3 ModelBuildContext | SHIPPED | G2 | — |
| #4 InvestmentIdea | SHIPPED | G1, G14 | — |
| #5 ProcessTemplate | SHIPPED | G7, G12 | `StrategyBias` (provided to #9) |
| #6 ModelInsights/PriceTarget | SHIPPED | G3, G4 | — |
| #7 IndustryResearchTools | NEEDS DESIGN | G5 (tools side) | Possibly — wiki industry-structure / competitive-advantage articles |
| #8 EDGAR/FMP Precedence | NEEDS DESIGN | G8 | — |
| **#9 KnowledgeWiki (THIS PLAN)** | **DRAFT R4** | **G6** | — |
| #10 ResearchEditorialPipeline | NEEDS DESIGN | G10 | Methodology citations in rendered editorial output |
| **#5b ExtensibleStrategyCategory** | **SHIPPED 2026-04-26** | **G16 (NEW)** | Extends `StrategyBias` → registered set; this plan's `process_template_categories` field auto-picks-up. Independent — either order. |

Plan #9 is a leaf node in the dependency graph: it consumes plan #5's `StrategyBias` literal but produces nothing that #7/#8 strictly require. Plan #10's editorial pipeline benefits from methodology-citation rendering but doesn't block on plan #9.

---

## 16. Test count target

- Sub-phase A: ~15 tests (Pydantic validation per field)
- Sub-phase B: ~10 tests (loader + index)
- Sub-phase C: ~8 tests (lookup combinations)
- Sub-phase D: ~12 tests (4 MCP tools × happy + error paths)
- Sub-phase E: 0 new tests (verification via F's gate)
- Sub-phase F: 1 omnibus + ~5 unit-level (registry parse, slug existence)
- ~~Sub-phase G~~: cut in R1
- Sub-phase H: 0 (docs only)
- Sub-phase I: 0 (docs only)

**Estimate**: ~46–50 new tests cumulative (G removed).

---

## 17. Acceptance gates

Plan ships when:

- [ ] All Pydantic contracts (§4) imported in `schema/__init__.py`, type-checked.
- [ ] Loader (§5) parses every existing methodology + wiki file without error (62 wiki + 2 methodology + future authoring).
- [ ] **R1 — Loader root resolves correctly through real memory lifecycle**: `get_methodology_root()` returns `get_legacy_workspace_dir() / "notes/methodology"`; smoke test calls it from a non-test process boot path and confirms the index loads.
- [ ] **R1 — Lenient runtime behavior verified**: a deliberately-malformed methodology file in the workspace logs a warning and is skipped; `get_methodology_index()` continues to return a valid index for the well-formed files.
- [ ] **R1 — Deterministic ordering**: `find_methodology(...)` returns results in `name`-asc; `lookup_wiki(...)` returns results in `(type, slug)`-asc. Tested against fixture.
- [ ] **R1 — Top-level legacy files explicitly excluded**: loader skips `notes/methodology/{investment_process,black_book,software_valuation}.md` per §13.1 #12; covered by a unit test.
- [ ] CI gate (§9) passes with backfilled units (§8). Per §3.5: concept slug + tag-registry membership + `process_template_categories` validity = error; `related`, `prerequisites`, `case_studies` ticker/slug, `cases` ticker/slug = warning. Aligned with §9.2 R2 split.
- [ ] 4 MCP tools (§7) callable end-to-end via the gateway, return typed `format="agent"` results.
- [ ] `SKILL_CONTRACT_MAP.md` (§11) updated; opt-in consumer list (`position-initiation`, `/thesis-consultation`, `/thesis-pre-mortem`, `earnings-review`) documented per §13.1 #13.
- [ ] Master plan §6.7 + §12 SHIPPED row updated; `docs/TODO.md` V2.P9d row marked SHIPPED.
- [ ] Codex PASS R≥1 on this plan.

---

## 18. Codex review request

Send to Codex with:
- This file
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` (master)
- `AI-excel-addin/docs/KNOWLEDGE_LAYER_DESIGN.md`
- `AI-excel-addin/docs/KNOWLEDGE_LAYER_WIKI_DESIGN.md`
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`
- `AI-excel-addin/schema/process_template.py` (StrategyBias source)
- `AI-excel-addin/schema/investment_idea.py` (StrategyBias usage)

**Asks for Codex (R2 — most R0/R1 questions now closed)**:

R0/R1 closed: two-field design (held), sub-phase G (cut), legacy files (excluded), `qualitative_factors` auto-prepop (no), index lifecycle (singleton + rebuild hook), `MemoryStoreFactory` interaction (curated path via `get_legacy_workspace_dir()`).

Remaining open (§13.2):
1. **`MethodologyUnit.tools` field validation** — informational vs. live MCP tool registry check. R2 keeps informational.
2. **Tag registry placement** — `schema/methodology_tag_registry.yaml` vs. `notes/methodology/_tag_registry.md`. R2 keeps `schema/`.
3. **`schema_version` strategy** — class-level default vs. frontmatter field. R2 keeps class-level.
4. **Cross-type `related` resolution at 200+ articles** — confirmed cheap at 62; revisit threshold.

**Reviewer note**: encourage local execution. Actually load the live workspace tree and verify `MethodologyIndex.load(get_methodology_root())` succeeds against today's 2 units + 62 wiki articles before approving.

---

## 19. Change log

- **R0** (2026-04-25) — Initial draft. Two-field categorization design (§3.1). Strict-CI / lenient-runtime split (§9.4). Sub-phase G marked optional pending Codex feedback. Awaiting first Codex round.
- **R1** (2026-04-25) — Codex R0 returned FAIL with 9 findings (2 High, 3 Medium, 4 Low). Fixes:
  - **High #1** (§3.2, §3.5, §4.2, §9.2): `WikiArticle.related` accepts any wiki slug (concepts, cases, frameworks, patterns) per live data; `WikiArticle.cases` documented as UPPERCASE ticker symbols, not slugs; CI gate distinguishes error (concept/related) vs warning (prerequisite/ticker).
  - **High #2** (§5.3, §5.4, §13.1 #8): Methodology root pinned to `get_legacy_workspace_dir() / "notes/methodology"` (curated read-only, not per-user `MemoryStoreFactory` path). Added `rebuild_methodology_indexes()` admin/test hook.
  - **Medium #3** (§3.5, §13.1 #10): Prerequisite existence check downgraded from error to warning (only 2 of ~20 units exist; tightening is a follow-up).
  - **Medium #4** (§13.1 #12): Top-level legacy files (`investment_process.md`, `black_book.md`, `software_valuation.md`) permanently excluded from typed loading.
  - **Medium #5** (§2, §10, §16, §17): Sub-phase G (risk_module MCP) cut. Total estimate down from ~5.25 to ~4.75 days.
  - **Low #6** (§3.1, §4.4): Wording tweak — `process_template_categories` validates against current `StrategyBias` implementation (literal pre-#5b, registry post-#5b), not a fixed enum. Test case rejects clearly-bogus string instead of `"growth"`.
  - **Low #7** (§5.4): `rebuild_methodology_indexes()` admin/test hook added; no watcher in v1.
  - **Low #8** (§13.1 #13, §11.2): No auto-prepopulation of `qualitative_factors` from methodology bodies. Specific opt-in consumer list documented (`position-initiation`, `/thesis-consultation`, `/thesis-pre-mortem`, `earnings-review`).
  - **Low #9** (§17): 4 new acceptance gates — root resolution through real memory lifecycle, lenient runtime, deterministic ordering, legacy-file exclusion.
  - Open questions narrowed (§13.2): legacy files locked, sub-phase G cut, index lifecycle confirmed; remaining: tools-field validation, tag registry placement, schema_version strategy, cross-type `related` resolution at 200+ articles.
- **R2** (2026-04-25) — Codex R1 returned FAIL with 5 findings (3 High, 1 Medium, 1 Medium-stale). Fixes:
  - **High #1** (§3.2, §3.5, §4.2): `WikiArticle.cases` accepts MIXED shape (UPPERCASE tickers AND lowercase slugs) per live data. Verified: `concepts/financial-models.md` has `[PCTY, coffee-shop, tradeweb]`. Resolution tries slug-as-given first, then ticker-fallback `value.lower()` only if `value` matches `^[A-Z]+$`. Both warning severity in CI.
  - **High #2** (§9.2): CI gate aligned with §3.5 severity table. Errors: concept slug, tag membership, `process_template_categories` validity, legacy-file exclusion regression. Warnings: `related`, `prerequisites`, `case_studies`, `cases`. R1 §9.2 contradicted §3.5 (still said wiki slugs / prerequisites = error); R2 §9.2 IS §3.5 made concrete.
  - **High #3** (§3.5 `related` row): `WikiArticle.related` existence check downgraded from error to warning. Reason: full-tree scan found 2 known-missing slugs in live data — `concepts/scalability.md → gross-margin` and `frameworks/decision-making-system.md → price-scenarios`. Verified: neither file exists. Promoting to error blocks ship today; warning lets CI pass while flagging for author follow-up.
  - **Medium #4** (§5.2): Loader pseudocode now has explicit `LEGACY_EXCLUDE = {"investment_process", "black_book", "software_valuation"}` frozenset and skips top-level legacy files at `path.parent == root and path.stem in LEGACY_EXCLUDE`. R1 had decision-locked the exclusion (§13.1 #12) but the pseudocode still walked them via `rglob`.
  - **Medium #5** (§7.5, §15, §18): Stale R0 wording swept. §7.5 now uses `"not_a_real_category"` not `"growth"`. §15 row updated DRAFT R0 → DRAFT R2. §18 ask list rewritten — closed R0/R1 questions removed; only the 4 genuinely-open ones in §13.2 remain.
- **R3** (2026-04-25) — Codex R2 returned FAIL with 5 consistency-only findings (3 High, 2 Medium). All cross-section staleness — no design changes:
  - **Line 63 / §2 row F**: CI gate description still listed `concepts/related = error`; corrected to `concepts + tag-registry + process_template_categories = error; related + prerequisites + case_studies + cases = warning per §3.5`.
  - **Line 276 / §4.2 pseudocode comment**: `cases` field comment still said "UPPERCASE ticker symbols (not slugs)"; corrected to "MIXED — UPPERCASE tickers OR lowercase case-article slugs".
  - **Line 442 / §5.2 loader policy**: still framed top-level legacy file exclusion as "Open question for Codex"; corrected to reference locked decision §13.1 #12 + `LEGACY_EXCLUDE` frozenset.
  - **Line 746 / §13.1 #9 + #11**: still said `WikiArticle.cases` are "UPPERCASE ticker symbols, not slugs"; rewrote both to reflect MIXED shape and warning severity for `related`.
  - **Line 852 / §18**: stray numbered-7 leftover from R0 ("Encourage local execution") was contradicting "only the 4 open items" claim; converted to non-numbered "Reviewer note" so open count stays at 4.
- **R4** (2026-04-25) — Codex R3-final returned FAIL on 3 stale live-body references (and confirmed §15 plan #5b row updated to R3 was correct). Fixes:
  - **§1 deliverable #3**: text claimed CI "fails" on broken `case_studies` and `prerequisites`; corrected to fail-on-`concepts` only and warn-on-`case_studies`/`prerequisites`/`related`/`cases` per §3.5.
  - **§3.2 `MethodologyUnit.case_studies` comment**: said "ticker symbols (uppercase)"; corrected to "MIXED: UPPERCASE tickers OR lowercase case-article slugs (§3.5)".
  - **§8.2 methodology unit `_template.md`**: example `case_studies: []` line said "ticker symbols"; corrected to "UPPERCASE tickers OR case-article slugs (mixed; §3.5)".
  - Plan #5b row in §15 series table also updated DRAFT R0 → DRAFT R3 (caught earlier in R3-final sub-pass).
- **R4-post-A** (2026-04-25, post sub-phase A ship) — implementation feedback. Codex R-impl noted that the `name` regex `^[a-z][a-z0-9-]*$` accepts trailing dashes (e.g. `"abc-"` matches), but §4.4 tests called for "rejects trailing dashes". Codex chose to keep the regex and add a supplementary `_validate_name` field validator. Plan §4.2 pseudocode updated to reflect this — regex + small validator that raises on `value.endswith("-")`. This is the shape that shipped in commit `cd1b389`. Tightening the regex itself to disallow trailing dash (e.g. `^[a-z]([a-z0-9-]*[a-z0-9])?$`) is harder to read; the validator is more legible and surfaces a clearer error.
- **R4-post-B** (2026-04-25, post sub-phase B ship) — implementation feedback. Two normalization choices added to the loader to handle live-data shape:
  1. **`version: 1.0` (YAML float) → `str` cast.** YAML parses `1.0` as `float` by default; the `MethodologyUnit.version: str` field rejects floats. Loader casts `version` to `str` before passing to Pydantic. Trivial, no plan change needed.
  2. **`source_modules: [Bonus]` → alias `Bonus → 5`** (in `_SOURCE_MODULE_ALIASES` map). 11 wiki articles use the legacy `Bonus` token for cross-module / supplementary content (per `KNOWLEDGE_LAYER_DESIGN.md` SIA module structure: "Bonus (Pitch + Case Studies)"). The contract literal `1..7` rejects strings; aliasing to `5` was the pragmatic unblock. **Open follow-up**: the alias is semantically wrong — `Bonus` content is closer to module 7 (pitch) or genuinely cross-module. Sub-phase F (CI gate) should formalize either by (a) updating wiki frontmatter to numeric modules, or (b) extending the source-module schema with an `8` sentinel for supplementary content. Files affected: `wiki/cases/{gartner,millrose,msci,nextpower,silver}.md`, `wiki/concepts/{commodity-investing,ir-questions,special-situations}.md`, `wiki/frameworks/stock-pitch-structure.md`, `wiki/patterns/{investment-case-types,priced-to-perfection}.md`.
