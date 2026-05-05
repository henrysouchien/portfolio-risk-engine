# Plan #5b — Extensible Strategy Category Registry (Investment Schema Unification)

> Archived 2026-05-04 under `docs/planning/completed/` after shipped status verification.

**Status**: SHIPPED 2026-04-26 — sub-phases A + B + C + D + E + F SHIPPED 2026-04-26 (AI-excel-addin commits `ef52372`, `3b4c4b5`, `cdea623`, `30a1897`, `a6f7d0e`, `552af11`; risk_module commits include `c3e93191` for the cross-repo F side). Sub-phases G + H completed in the final migration-safety/docs batch.

**Last revised**: 2026-04-26 (SHIPPED — sub-phase G added `scripts/check_strategy_category_migration.py` with optional SQLite validation plus fixture-only fallback and permanent AI-excel-addin CI fixture tests. Sub-phase H updated master plan §6.5/§12, `SKILL_CONTRACT_MAP.md`, plan #9 cross-reference, and `docs/TODO.md` ship markers).

**Authoritative design reference**: `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.5 (extends the shipped ProcessTemplate design — adds extensibility hook to the existing `StrategyBias` concept).

**Companion docs**:
- `docs/planning/completed/PROCESS_TEMPLATE_PLAN.md` (plan #5, SHIPPED 2026-04-23) — the contract this plan extends
- `docs/planning/completed/KNOWLEDGE_WIKI_SCHEMA_PLAN.md` (plan #9) — coupled consumer; benefits directly when #5b ships
- `docs/planning/completed/INVESTMENT_IDEA_INGRESS_PLAN.md` (plan #4) — ships `InvestmentIdea.strategy` field
- `AI-excel-addin/schema/process_template.py` — `StrategyBias` definition + `InvestorProfile`
- `AI-excel-addin/schema/investment_idea.py` — `strategy` field on idea
- `AI-excel-addin/schema/thesis_shared_slice.py` — `StrategyValue` alias
- `AI-excel-addin/schema/enum_canonicalizers.py` — strategy normalization

**Closes** (new gap, not in master plan today):
**G16. Strategy categorization is not user-extensible.** `StrategyBias = Literal["value", "special_situation", "macro", "compounder"]` is a frozen Pydantic literal across 4 schema files. Plan #5 made the right call for v1 (typed, validated, narrow). For Hank as a multi-user product, this becomes a ceiling: users with GARP, dividend-income, activist, event-driven, quant, or sector-specialist styles can't author their own ProcessTemplates because `InvestorProfile.strategy_bias` rejects any value outside the 4 built-ins.

**Depends on**: Plan #5 ProcessTemplate (SHIPPED). Independent of plan #9 (KnowledgeWiki) — #5b can ship before, after, or alongside.

**Couples with plan #9**: plan #9's `MethodologyUnit.process_template_categories: list[StrategyBias]` automatically picks up the extended set once #5b lands, with no plan #9 code change. See §1.3 below.

---

## 1. Purpose & scope

Convert `StrategyBias` from a frozen `Literal` to a **registry-validated extensible identifier**, while preserving every property plan #5 cared about: type safety, no-typos validation, JSON wire-format stability, deterministic canonicalization.

**End state**:
- The 4 built-in categories (`value`, `special_situation`, `macro`, `compounder`) ship as immutable defaults — every persisted artifact remains valid; no data migration.
- Users / deployments can register additional categories (e.g., `growth`, `income`, `event_driven`, `quant`, `activist`, `garp`) via configuration.
- Pydantic still rejects unknown values (registry-membership check on every contract instance) — no garbage values land in storage.
- ProcessTemplates can declare `strategy_bias` to any registered ID, including user-defined ones.
- Plan #9's methodology lookup automatically surfaces units tagged with the expanded category set.

### 1.1 Non-goals (v1)

- **No removal of the 4 built-in defaults.** They stay locked as shipped IDs.
- **No template-default presets per category.** `growth` doesn't ship with a default seed-factor list; ProcessTemplates remain per-user-authored. Per-category defaults can be a follow-on plan.
- **No multi-tenant per-user registries (full SaaS).** v1 ships a single deployment-wide registry loaded from a YAML file. Per-user runtime registration is a follow-on.
- **No frontend UI for category authoring.** Registry edit = YAML edit + redeploy in v1.
- **No automatic canonicalization of user-typed natural-language input** (e.g., "Growth at a Reasonable Price" → `garp`). Aliases in the registry handle the 4 built-ins' legacy variants only; user-defined aliases are configurable per category but not heuristic.
- **No cross-process live reload.** Registry loaded at import time; updates require process restart.
- **No removal of `methodology_tags` (plan #9).** That field captures *content lenses* (`spinoff`, `s_curve_inflection`) — distinct axis from *investor styles*. Both stay.

### 1.2 What changes vs. plan #5 as shipped

| Concept | Plan #5 (shipped) | Plan #5b (this plan) |
|---|---|---|
| Type | `StrategyBias = Literal["value", "special_situation", "macro", "compounder"]` | `StrategyCategoryId = Annotated[str, AfterValidator(_check_registered)]` |
| Validation | Pydantic literal | Pydantic validator queries `StrategyCategoryRegistry.is_registered(value)` |
| Source of valid IDs | Hardcoded in 4 files | `schema/strategy_categories/defaults.yaml` (built-ins) + optional user config |
| Adding a category | Multi-file PR + migration | Append entry to YAML; restart |
| IDE autocomplete | Yes (Literal) | No (string) — mitigated by `category_ids()` helper for callers building UIs |
| Wire format stability | Locked at 4 | Locked at 4 built-ins; user IDs append-only by convention |

### 1.3 Coupling with plan #9

Plan #9 ships `MethodologyUnit.process_template_categories: list[StrategyBias]` consuming the `StrategyBias` literal. When #5b lands, that field's *type* changes (literal → registered-string), but plan #9's *Pydantic model code* doesn't change because both versions satisfy `list[StrategyBias]` import. Plan #9's CI gate (frontmatter linter) automatically validates against the live registry.

**Methodology unit author flow after #5b ships**:
1. Author wants to tag a unit for `growth` strategy.
2. Add `growth` to `schema/strategy_categories/defaults.yaml` (or user registry).
3. Add `growth` to the unit's `process_template_categories: [growth, compounder]`.
4. Plan #9's CI gate now passes; `find_methodology(category="growth")` returns the unit.

No plan #9 changes required. The two plans compose cleanly.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | Registry data model + YAML schema | `schema/strategy_categories/registry.py` (new); `defaults.yaml` (new) shipping the 4 built-ins; `StrategyCategory` Pydantic model with `id`, `display_name`, `aliases`, `description`. | ~0.5 day | — |
| B | Type-system change across schema | Replace `StrategyBias = Literal[...]` with `StrategyCategoryId = Annotated[str, AfterValidator(_validate_registered)]` in 4 files. Update fields on `InvestorProfile`, `InvestmentIdea.strategy`, `Thesis.strategy`, `HandoffArtifact.thesis.strategy`, `MethodologyUnit.process_template_categories` (plan #9). | ~1 day | A |
| C | Canonicalizer rewrite | Rewrite `enum_canonicalizers._STRATEGY_VALUES` + `canonicalize_optional_strategy` to lookup registry. Built-in aliases (`"Value"` → `value`) move to the registry's `aliases` field. | ~0.5 day | A |
| D | User registry layering (config-driven) | Optional `STRATEGY_CATEGORY_REGISTRY_PATH` env var loads supplemental categories from a deployment YAML. Built-ins always loaded first; user IDs append (must not collide with built-ins). | ~0.5 day | A |
| E | Test migration | Update every test that hardcoded the 4-string set to use `registry.builtin_ids()`. Add round-trip tests for user-registered categories. | ~1 day | A, B, C, D |
| F | Cross-repo propagation | Update risk_module TS types if any reference `StrategyBias` (likely auto-generated). Update gateway error classifier — new `StrategyCategoryUnknownError` typed error. Update MCP tool schemas that exposed `StrategyBias` in their input/output models. | ~0.5 day | B |
| G | Migration safety check | One-shot script that loads every persisted `Thesis`, `InvestmentIdea`, `HandoffArtifact`, `ProcessTemplate` row and asserts every `strategy` / `strategy_bias` / `process_template_categories` value resolves in the registry. Run pre-deploy. Should be a no-op (built-ins unchanged) but proves no data drift. | ~0.5 day | A, B |
| H | Docs | Master plan §6.5 update describing the registry; `SKILL_CONTRACT_MAP.md` checklist for "adding a new strategy category"; plan #9 §6.7 cross-reference; `TODO.md` row update. | ~0.25 day | A–G |

**Total estimate**: ~4.75 days.

### 2.1 Dependency graph

```
A (registry + defaults YAML)
├── B (type-system change across 4 schema files) ─── F (cross-repo TS / MCP / gateway)
│
├── C (canonicalizer rewrite — built-in aliases to registry)
│
├── D (user-config layering)
│
└── G (migration safety check) ─── depends on A + B

E (test migration) — depends on A, B, C, D
H (docs) — last
```

---

## 3. Cross-cutting concerns

### 3.1 Built-in vs. user categories — the contract

**The 4 built-ins are part of the shipped contract.** Their IDs (`value`, `special_situation`, `macro`, `compounder`) MUST NOT change, MUST NOT be removed, MUST NOT be aliased to a different canonical ID. Plan #5b enforces this in the registry loader: `defaults.yaml` is loaded as immutable; user YAML is loaded second and rejected if it tries to redefine a built-in ID.

**User categories are append-only by deployment convention.** The registry doesn't track tombstones — if a user removes a category from their config, any persisted artifact still carrying that ID becomes invalid on next read. v1 addresses this only via documentation: "Don't remove a category from the registry until no live data references it." A future plan could add tombstones / deprecation.

### 3.2 Registry data shape

```yaml
# schema/strategy_categories/defaults.yaml
# Aliases must be NORMALIZED-DISTINCT from the canonical id and from each other.
# Display-only variants (e.g. "Value" for id "value") are accepted as user input
# automatically via the canonical-id self-entry in _alias_to_id; they do NOT need
# to be listed in `aliases:`. List only forms whose normalized output differs
# from the canonical id (e.g. "value-investing" → "value_investing" ≠ "value").
version: 1.0
categories:
  - id: value
    display_name: Value
    aliases: [value-investing]
    description: Buying assets below intrinsic value; margin of safety; mean reversion.
  - id: special_situation
    display_name: Special Situation
    aliases: [special-situations]                      # plural form
    description: Spinoffs, restructurings, M&A arb, IPO post-lockup, forced selling.
  - id: macro
    display_name: Macro
    aliases: []                                        # no normalized-distinct alias
    description: Top-down driven by economic cycles, rates, currency, commodity flows.
  - id: compounder
    display_name: Compounder
    aliases: [compounder-quality, quality-compounder]
    description: Long-duration high-quality businesses with reinvestment runway.
```

```yaml
# example user override at /etc/hank/strategy_categories.yaml
# Same rule: aliases must be normalized-distinct from canonical id + each other.
version: 1.0
categories:
  - id: growth
    display_name: Growth
    aliases: []
    description: Earnings/revenue growth above market average; willing to pay multiple.
  - id: income
    display_name: Income
    aliases: [dividend, dividend-income]
    description: Yield-driven; dividend sustainability and growth as primary lens.
  - id: garp
    display_name: GARP
    aliases: [growth-at-reasonable-price]
    description: Growth at a Reasonable Price — quality + growth at sub-market multiple.
  - id: event_driven
    display_name: Event-Driven
    aliases: [events]                                  # `event-driven` ≡ canonical, drop
    description: Catalysts (earnings, M&A, regulatory) within fixed time horizon.
```

**ID format constraint**: `^[a-z][a-z0-9_]{1,30}$` — same as `template_id` in plan #5 for consistency.

### 3.3 Canonicalization

Existing `canonicalize_optional_strategy` hardcodes alias logic. Plan #5b replaces it with:

```python
def canonicalize_optional_strategy(value: object | None) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ValueError(f"strategy must be a string, got {type(value).__name__}")
    canonical = STRATEGY_REGISTRY.canonicalize(value)  # checks aliases, returns canonical id
    if canonical is None:
        valid_ids = ", ".join(sorted(STRATEGY_REGISTRY.all_ids()))
        raise ValueError(f"strategy must be one of: {valid_ids}; got {value!r}")
    return canonical
```

Behavior preserved for the 4 built-ins (legacy `"Value"`, `"Special Situation"` still canonicalize). User aliases work the same way.

### 3.4 Type system — `Literal` to registered-string

```python
# schema/process_template.py — BEFORE (today)
StrategyBias = Literal["value", "special_situation", "macro", "compounder"]

# schema/process_template.py — AFTER (#5b)
from typing import Annotated
from pydantic import AfterValidator
from .strategy_categories.registry import validate_strategy_category_id

StrategyCategoryId = Annotated[str, AfterValidator(validate_strategy_category_id)]
# Backward-compat alias — plan #5b keeps the old name available so plan #9 imports don't break:
StrategyBias = StrategyCategoryId
```

The alias keeps every existing import working. Downstream code (plan #9, plan #6, etc.) keeps using `StrategyBias`; the alias resolves to the new validated string type.

### 3.5 Migration safety

Built-in IDs are unchanged → every persisted `strategy` value validates as before. No DB migration. Sub-phase G's safety script proves this empirically across all live tables before deployment.

The only edge case: if a user has somehow persisted a non-canonical alias (e.g., literal `"Value"` in a row that bypassed the canonicalizer), it must still validate. Plan #5b's canonicalizer accepts aliases on read — so `"Value"` reads as `value` going forward, same as today.

### 3.6 IDE autocomplete loss — mitigation

Loss of `Literal` autocomplete is a real DX regression. Mitigation:

```python
# schema/strategy_categories/registry.py
def builtin_ids() -> tuple[str, ...]:
    return ("value", "special_situation", "macro", "compounder")

def all_ids() -> tuple[str, ...]:
    return tuple(STRATEGY_REGISTRY.ids())  # built-ins + user
```

UIs and CLIs that need a dropdown call `builtin_ids()` (stable) or `all_ids()` (dynamic). Tests that previously hardcoded the 4 strings call `builtin_ids()`. The Literal-autocomplete moments where a developer typed `strategy_bias=` and got 4 options inline are gone — accepted cost.

### 3.7 Wire-format stability

Built-in IDs locked → external consumers (frontend, MCP clients, downstream systems) keep parsing the same strings. User IDs are additive — clients that don't know about `growth` simply receive `"growth"` as a string and either render it or fall back to `display_name` from the registry. Sub-phase F adds a registry-fetch MCP tool so clients can resolve IDs to display names.

---

## 4. Sub-phase A — Registry data model + YAML

### 4.1 Goal

Ship the registry primitives + defaults.yaml. Importable, validated. No consumers yet.

### 4.2 Design

```python
# schema/strategy_categories/registry.py
from pathlib import Path
import os
import re
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_FROZEN = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID_PATTERN = r"^[a-z][a-z0-9_]{1,30}$"

# R1 — single shared normalizer (Codex R0 should-fix #3); aligns with existing
# canonicalizer at AI-excel-addin/schema/enum_canonicalizers.py:21:
#     re.sub(r"[\s\-_]+", "_", value.strip().lower())
# Used by ids (consistency check), aliases (alias->id lookup), and canonicalize().
_NORMALIZE_RE = re.compile(r"[\s\-_]+")


def _normalize(value: str) -> str:
    return _NORMALIZE_RE.sub("_", value.strip().lower())


class StrategyCategory(BaseModel):
    id: str = Field(pattern=_ID_PATTERN)
    display_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    is_builtin: bool = False  # set by loader, not by YAML author

    model_config = _FROZEN


class StrategyCategoryRegistry:
    """Singleton-style registry. Load once at import; immutable thereafter."""

    def __init__(self) -> None:
        self._by_id: dict[str, StrategyCategory] = {}
        self._alias_to_id: dict[str, str] = {}  # case-folded alias -> canonical id
        self._load_defaults()
        self._load_user_overrides()

    def _load_defaults(self) -> None:
        path = Path(__file__).parent / "defaults.yaml"
        for cat in self._parse(path, mark_builtin=True):
            self._add(cat, builtin=True)

    def _load_user_overrides(self) -> None:
        env_path = os.environ.get("STRATEGY_CATEGORY_REGISTRY_PATH")
        if not env_path:
            return
        for cat in self._parse(Path(env_path), mark_builtin=False):
            if cat.id in self._by_id and self._by_id[cat.id].is_builtin:
                raise ValueError(
                    f"User registry cannot redefine built-in category {cat.id!r}"
                )
            self._add(cat, builtin=False)

    def _add(self, cat: StrategyCategory, *, builtin: bool) -> None:
        # R2 — validate fully BEFORE any mutation (Codex R1 finding #2).
        # R3 — same-batch duplicate alias detection (Codex R2 finding).
        # R4 — distinguish alias-equals-own-canonical (idempotent, allowed) from
        #      alias-equals-another-alias-in-this-category (typo, rejected).
        #      Codex R3 finding: defaults YAML has aliases like ["Value", "VALUE",
        #      "value-investing"] for id="value"; both "Value" and "VALUE"
        #      normalize to "value" which equals the canonical id. R3 rejected
        #      this; R4 allows it (no-op writes to _alias_to_id["value"] = "value").
        if cat.id in self._by_id:
            raise ValueError(f"Duplicate category id {cat.id!r}")

        canonical_normalized = _normalize(cat.id)

        # Existing alias map can NOT have a different category claiming this
        # canonical-id form already.
        existing_owner = self._alias_to_id.get(canonical_normalized)
        if existing_owner is not None and existing_owner != cat.id:
            raise ValueError(
                f"Category id {cat.id!r} (normalized {canonical_normalized!r}) "
                f"collides with existing alias of category {existing_owner!r}"
            )

        # Validate every alias against:
        #   (a) existing aliases of OTHER categories (cross-category collision)
        #   (b) existing canonical ids of OTHER categories
        #   (c) other aliases ALREADY SEEN in this category's own alias list
        # WITHOUT mutating yet.
        # R4: aliases that normalize to this category's OWN canonical id are
        # allowed (no-op writes), but they still count toward seen_aliases for
        # purposes of detecting *true* duplicates within the alias list.
        seen_alias_normalized: set[str] = set()
        for alias in cat.aliases:
            normalized = _normalize(alias)

            # (a) Cross-category alias collision
            existing = self._alias_to_id.get(normalized)
            if existing is not None and existing != cat.id:
                raise ValueError(
                    f"Alias {alias!r} collides between {existing!r} and {cat.id!r}"
                )

            # (b) Cross-category canonical-id collision
            normalized_canonical_owner = next(
                (cid for cid in self._by_id if _normalize(cid) == normalized),
                None,
            )
            if normalized_canonical_owner is not None and normalized_canonical_owner != cat.id:
                raise ValueError(
                    f"Alias {alias!r} (normalized {normalized!r}) collides with canonical id "
                    f"of category {normalized_canonical_owner!r}"
                )

            # (c) Same-category alias-list duplicate (R3+R4):
            #     - alias normalized == another previously-seen alias normalized → reject (typo)
            #     - alias normalized == canonical_normalized → allowed, but only ONCE
            #       (if "Value" appears AND "VALUE" appears for id="value", reject as duplicate)
            if normalized in seen_alias_normalized:
                raise ValueError(
                    f"Alias {alias!r} (normalized {normalized!r}) appears more than once "
                    f"for category {cat.id!r}"
                )
            seen_alias_normalized.add(normalized)

        # All checks passed — commit.
        cat = cat.model_copy(update={"is_builtin": builtin})
        self._by_id[cat.id] = cat
        # Always seed the canonical-id self-entry first.
        self._alias_to_id[canonical_normalized] = cat.id
        # Then write each alias normalized form. Aliases whose normalized form
        # equals canonical_normalized are no-op overwrites of the same value —
        # harmless.
        for alias in cat.aliases:
            normalized = _normalize(alias)
            self._alias_to_id[normalized] = cat.id

    def is_registered(self, category_id: str) -> bool:
        return category_id in self._by_id

    def canonicalize(self, value: str) -> str | None:
        # R1 — uses shared normalizer (matches enum_canonicalizers.py collapsing semantics)
        return self._alias_to_id.get(_normalize(value))

    def all_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id.keys()))

    def builtin_ids(self) -> tuple[str, ...]:
        return tuple(sorted(c.id for c in self._by_id.values() if c.is_builtin))

    def get(self, category_id: str) -> StrategyCategory | None:
        return self._by_id.get(category_id)


# Module-level singleton
STRATEGY_REGISTRY = StrategyCategoryRegistry()


def validate_strategy_category_id(value: str) -> str:
    """Pydantic AfterValidator. Returns canonical id or raises."""
    if not isinstance(value, str):
        raise ValueError(f"strategy category must be a string, got {type(value).__name__}")
    if STRATEGY_REGISTRY.is_registered(value):
        return value  # already canonical
    canonical = STRATEGY_REGISTRY.canonicalize(value)
    if canonical is None:
        valid = ", ".join(STRATEGY_REGISTRY.all_ids())
        raise ValueError(f"unknown strategy category {value!r}; valid: {valid}")
    return canonical
```

### 4.3 Files to create / modify

- `AI-excel-addin/schema/strategy_categories/__init__.py` (new)
- `AI-excel-addin/schema/strategy_categories/registry.py` (new, ~150 lines)
- `AI-excel-addin/schema/strategy_categories/defaults.yaml` (new, ~30 lines per §3.2)

### 4.4 Tests

- `tests/schema/test_strategy_category_registry.py`:
  - Built-in 4 load and resolve.
  - Aliases canonicalize ("Value" → value, "special-situation" → special_situation).
  - Unknown ID raises.
  - User override via env var loads successfully.
  - User override rejected if it redefines a built-in.
  - Alias collision across categories raises.
  - `validate_strategy_category_id` returns canonical form for alias input.

---

## 5. Sub-phase B — Type-system change across schema

### 5.1 Goal

Swap `Literal` for `Annotated[str, AfterValidator(...)]` across 4 schema files. Preserve `StrategyBias` name as alias for downstream compat.

### 5.2 Concrete edits

**`schema/process_template.py`** (line 32):
```diff
-StrategyBias = Literal["value", "special_situation", "macro", "compounder"]
+from typing import Annotated
+from pydantic import AfterValidator
+from .strategy_categories.registry import validate_strategy_category_id
+
+StrategyCategoryId = Annotated[str, AfterValidator(validate_strategy_category_id)]
+StrategyBias = StrategyCategoryId  # backward-compat alias
```

**`schema/investment_idea.py`** (line 76):
```diff
-    strategy: Literal["value", "special_situation", "macro", "compounder"] | None = None
+    strategy: StrategyCategoryId | None = None
```

**`schema/thesis_shared_slice.py`** (line 17):
```diff
-StrategyValue = Literal["value", "special_situation", "macro", "compounder"]
+StrategyValue = StrategyCategoryId  # alias preserved
```

**`schema/enum_canonicalizers.py`**: rewrite per §3.3 — pull `_STRATEGY_VALUES` frozenset out, replace logic with registry lookup. Function signature unchanged so callers don't break.

### 5.3 Files to create / modify

- `AI-excel-addin/schema/process_template.py` — type alias swap.
- `AI-excel-addin/schema/investment_idea.py` — field type swap.
- `AI-excel-addin/schema/thesis_shared_slice.py` — alias swap.
- `AI-excel-addin/schema/enum_canonicalizers.py` — function rewrite (registry-driven).

### 5.4 Tests

**R1 correction** (Codex R0 should-fix #1, **R2 expansion** per Codex R1 finding #1): the claim "existing tests pass without modification" is **false** for snapshot tests. Four specific snapshot pins exist:

- `AI-excel-addin/tests/schema/test_process_template_boundary.py:90` — pins ProcessTemplate JSON Schema including `StrategyBias` enum values
- `AI-excel-addin/tests/schema/test_investment_idea_boundary.py:100` — pins InvestmentIdea JSON Schema including `strategy` enum values
- `AI-excel-addin/tests/integration/test_shared_slice_isomorphism.py:195` — pins `thesis_v1_0.schema.json` (R2 — Codex R1 found this; `Thesis.strategy` field uses `StrategyValue` alias)
- `AI-excel-addin/tests/integration/test_shared_slice_isomorphism.py:199` — pins `handoff_v1_1.schema.json` (R2 — same; `HandoffArtifact.thesis.strategy` uses `StrategyValue`)

All four will fail when `Literal[...]` becomes `Annotated[str, AfterValidator(...)]` because Pydantic's generated JSON Schema for the latter does NOT include an `enum` field. Snapshot regeneration is required for all four.

**R2 — also confirmed not affected**: `business_model_v1_0` snapshot is pinned but has no strategy-category field; not affected by this change.

**Plan**:
- Regenerate snapshots after the type change.
- Manual review of the diff to confirm only the enum-removal is captured (not unrelated drift).
- Add a snapshot-review acceptance gate (§16).
- All other tests in `test_process_template.py`, `test_investment_idea.py`, `test_thesis.py` pass without modification because they assert behavior, not schema shape.

**New tests**:
- Constructing `InvestorProfile(strategy_bias="not_a_real_id")` — always fails (R1: chosen instead of `"growth"` since `"growth"` validity is environment-dependent post-#5b).
- User-registered category flows through `InvestmentIdea` → `Thesis` → `HandoffArtifact` round-trip.
- JSON serialization of user category produces canonical ID string.
- `_normalize("Special Situation")` == `_normalize("special-situation")` == `_normalize("special_situation")` — confirms shared normalizer collapses all three variants identically.
- Loader rejects duplicate IDs.
- Loader rejects alias collisions across categories.
- Loader rejects alias normalized form equal to another category's canonical id.

---

## 6. Sub-phase C — Canonicalizer rewrite

Already detailed in §3.3. Files: `schema/enum_canonicalizers.py`. Tests: ensure title-case / kebab-case / underscore / snake-case all canonicalize for both built-ins AND user-registered categories.

---

## 7. Sub-phase D — User registry layering (config-driven)

### 7.1 Design

`STRATEGY_CATEGORY_REGISTRY_PATH` env var. If set, points to a YAML file with the same shape as `defaults.yaml`. Loaded after defaults; user-defined IDs cannot collide with built-in IDs.

### 7.2 Tests

- Env var unset → only built-ins.
- Env var set to valid path → built-ins + user categories.
- Env var set to file with built-in collision → loader raises at import.
- Env var set to non-existent path → loader raises at import (fail-fast — preferable to silently dropping user config).

---

## 8. Sub-phase E — Test migration

### 8.1 Goal

Find every test file that hardcoded the 4-string set. Replace with `registry.builtin_ids()` — keeps tests stable when the registry expands.

### 8.2 Concrete sweep

```
grep -rn "value.*special_situation.*macro.*compounder" tests/
grep -rn "_STRATEGY_VALUES\|_ALLOWED_STRATEGIES" .
```

Each match → either replace with `registry.builtin_ids()` OR explicitly assert built-ins-only (whichever the test intends).

---

## 9. Sub-phase F — Cross-repo propagation

### 9.1 Risk_module / frontend TS types

**R1 correction** (Codex R0 should-fix #2): frontend strategy options are **hand-maintained**, not codegen-generated. Two specific consumers identified:

| File | Symbol | Action |
|---|---|---|
| `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx` | `STRATEGY_OPTIONS` | Replace static array with runtime fetch from new MCP tool `list_strategy_categories`. Cache once per session. |
| `frontend/packages/ui/src/components/research/AddFactorModal.tsx` | `STRATEGY_FACTOR_SUGGESTIONS` | Keep the suggestion *map* as built-in/default fallback (it's a per-category factor preset, not a category list). New categories added via #5b registry simply have no suggestion entry until an author adds one. Don't make this fully dynamic in v1. |

### 9.2 New MCP tool

`list_strategy_categories` — returns the live registry. Frontend dropdowns render dynamic options. Risk_module gateway adds typed-error class `StrategyCategoryUnknownError` to its classifier.

**R1 — return shape** (Codex R0 should-fix #8). **R4 — examples updated to match the §3.2 normalized-distinct convention** (Codex R4 finding #2):
```python
{
  "categories": [
    {
      "id": "value",
      "display_name": "Value",
      "aliases": ["value-investing"],
      "description": "...",
      "is_builtin": true,
    },
    {
      "id": "growth",
      "display_name": "Growth",
      "aliases": [],
      "description": "...",
      "is_builtin": false,
    },
  ]
}
```
`is_builtin` enables frontends and admin tools to render locked vs. deployment-defined categories differently (e.g., disable delete on built-ins).

### 9.3 Files to create / modify

- `AI-excel-addin/mcp_servers/agents_mcp/strategy_category_tool.py` (new)
- `risk_module/services/research_gateway.py` — typed-error map extension
- `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx` — `STRATEGY_OPTIONS` becomes dynamic.
- `frontend/packages/ui/src/components/research/AddFactorModal.tsx` — confirm `STRATEGY_FACTOR_SUGGESTIONS` stays as built-in fallback (no behavior change required, but the surrounding context now allows registered categories with no suggestion entry).

---

## 10. Sub-phase G — Migration safety check

### 10.1 Goal

Pre-deployment proof that no live data is invalidated by the type swap.

### 10.2 Script

```python
# scripts/check_strategy_category_migration.py
from schema.strategy_categories.registry import STRATEGY_REGISTRY

def check_table(table, field):
    rows = run_query(f"SELECT id, {field} FROM {table} WHERE {field} IS NOT NULL")
    bad = [(r.id, r[field]) for r in rows if not STRATEGY_REGISTRY.canonicalize(r[field])]
    if bad:
        raise ValueError(f"{table}.{field}: unresolvable values {bad[:10]}")
    print(f"{table}.{field}: {len(rows)} rows OK")

check_table("theses", "strategy")
check_table("investment_ideas", "strategy")
check_table("handoff_artifacts", "thesis_strategy")
check_table("process_templates", "investor_profile_strategy_bias")
```

Run as a pre-deploy gate. Should be a no-op (built-ins unchanged) — proves it.

**R1 — also add permanent CI test** (Codex R0 should-fix #9). The pre-deploy script validates *live* data and can't run in CI. CI gets a fixture-based equivalent at `tests/test_strategy_category_fixtures.py`:

- Loads `defaults.yaml` and asserts every entry parses.
- Loads a known-good user fixture and asserts no built-in collision.
- Loads a known-bad user fixture (built-in collision) and asserts the loader raises.
- For each shipped artifact fixture (Thesis, InvestmentIdea, HandoffArtifact, ProcessTemplate test fixtures), asserts every `strategy` / `strategy_bias` / `process_template_categories` value resolves in the registry.

CI prevents loader/canonicalizer regressions; live-data script remains the pre-deploy gate.

---

## 11. Sub-phase H — Docs

### 11.1 Master plan

Patch `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md`:

- §6.5 — add a paragraph: *"Plan #5b (`EXTENSIBLE_STRATEGY_CATEGORY_PLAN.md`) extends `StrategyBias` to a registry-validated string for multi-user product use. Built-in 4 unchanged; users append via deployment YAML. Plan #5's frozen-enum design is preserved for the built-ins."*
- §12 — add row 5b in the Follow-On table.

### 11.2 SKILL_CONTRACT_MAP

Add checklist for "adding a new strategy category":
1. Append entry to `schema/strategy_categories/defaults.yaml` (built-in) or user registry.
2. Run migration safety check (§10).
3. If new built-in: PR review + master plan §6.5 update.

### 11.3 Plan #9 cross-reference

Edit `docs/planning/completed/KNOWLEDGE_WIKI_SCHEMA_PLAN.md` §3.1 to note: *"Once plan #5b ships, `process_template_categories` accepts any registered category, not just the 4 built-ins. Two-field design (categories + tags) remains because content-lens taxonomy is a different axis from investor-style taxonomy."*

### 11.4 TODO

`docs/TODO.md` V2.P9 row addition:
> | V2.P9f | **Plan #5b: `EXTENSIBLE_STRATEGY_CATEGORY_PLAN.md`** — registry-validated `StrategyBias` for multi-user product extensibility | `SHIPPED 2026-04-26` | `docs/planning/completed/EXTENSIBLE_STRATEGY_CATEGORY_PLAN.md` (R5 PASS, SHIPPED). Master design: `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.5 + §12 ship notes. | Closes G16 — strategy categorization extensibility for multi-user. Built-in 4 unchanged; user categories append-only via YAML config. Required for any user beyond Henry to author ProcessTemplates with their own investment style. Couples with plan #9 (`process_template_categories` field auto-picks-up wider set). Deps: plan #5 ProcessTemplate (shipped). |

---

## 12. Decisions

### 12.1 Locked

1. **Built-in 4 stay locked.** No removal, no rename, no alias-redefinition.
2. **User categories append-only by convention.** v1 doesn't enforce tombstones.
3. **`StrategyBias` name preserved as alias indefinitely** (R1, Codex R0 should-fix #5). No runtime deprecation warning — creates noise without data-safety gain. Convention: new code uses `StrategyCategoryId`; legacy/imported contracts may use `StrategyBias`. Documented in `SKILL_CONTRACT_MAP.md`.
4. **Single deployment-wide registry in v1.** Per-user runtime registration is a follow-on plan.
5. **Aliases canonicalize via registry, not heuristics.** No fuzzy matching.
6. **Fail-fast on bad config.** Missing env-var path or built-in collision raises at import — better than silently degrading.
7. **R1 — Shared normalizer** (Codex R0 should-fix #3). One regex `re.sub(r"[\s\-_]+", "_", value.strip().lower())` used for ids, aliases, and `canonicalize()`. Matches existing `enum_canonicalizers.py:21` semantics exactly so behavior is identical pre/post #5b.
8. **R1 — Loader integrity checks at boot** (Codex R0 should-fix #4). Duplicate id, alias collision, alias normalized form equal to another canonical id all raise at registry construction. No silent shadow.
9. **R1 — Per-category metadata stays minimal** (Codex R0 should-fix #6 confirmed). `StrategyCategory` carries `id`, `display_name`, `aliases`, `description`. No `default_seed_factors`, `default_valuation_methods`, etc. — those live on `ProcessTemplate`.
10. **R1 — `list_strategy_categories` MCP tool exposes `is_builtin`** (Codex R0 should-fix #8) — frontends/admins render locked-vs-deployment categories differently.

### 12.2 Open questions — closed in R2

All R0 + R1 questions resolved by Codex review:

- Storage (YAML — confirmed)
- Live reload (no — confirmed)
- Per-category metadata (minimal — confirmed)
- MCP shape (`is_builtin` — confirmed)
- `StrategyBias` alias (kept indefinitely, no warning — confirmed)
- Migration script (pre-deploy + CI fixture both — confirmed)
- Tombstone enforcement (no warnings without explicit tombstone list — Codex R1 confirmed; pre-deploy script sufficient for v1)
- Frontend `STRATEGY_FACTOR_SUGGESTIONS` (kept out of registry; empty for user categories OK; dynamic dropdown is the required UX — Codex R1 confirmed)

No open questions for R2 re-review beyond verifying the R2 fixes themselves.

---

## 13. Out of scope (v1)

| Non-goal | Why | Future plan? |
|---|---|---|
| Per-user runtime category registration | Multi-tenant SaaS concern; v1 deployment-wide is fine | Plan #5c if/when SaaS |
| Per-category seed-factor presets | ProcessTemplate is the seed-factor surface — per-user-authored | Maybe — depends on whether users want defaults |
| Frontend UI for category authoring | YAML edit + redeploy is fine for v1 | When per-user runtime lands |
| Tombstones / deprecation | Append-only convention covers v1 | Plan #5c if data integrity at scale |
| Heuristic / fuzzy alias matching | Surprise-prone; explicit aliases are safer | No |
| Per-category translations / i18n | English-only product today | Far future |
| Versioned categories (e.g., `value@v2`) | YAGNI for v1 | No |

---

## 14. Plan #5b vs. plan #9 — composition

| Concept | Plan #9 ships | Plan #5b ships |
|---|---|---|
| `MethodologyUnit.process_template_categories` | List of `StrategyBias` (today: 4 values) | Same field; type expands to registered set |
| `MethodologyUnit.methodology_tags` | Free-form list, registry-validated | Untouched |
| `find_methodology(category=...)` | Accepts any `StrategyBias` value | Accepts any registered category id |
| `InvestorProfile.strategy_bias` | Restricted to 4 | Extensible |
| Order they ship | Independent | Independent |

Both plans can ship in either order. If #9 ships first, methodology lookup works for the 4 built-ins. When #5b ships, the existing methodology units' frontmatter doesn't change — only newly-authored units can use new categories.

---

## 15. Test count target

- Sub-phase A: ~12 tests (registry primitives, alias collision, env var, builtin-vs-user)
- Sub-phase B: ~8 tests (round-trip across 4 contracts)
- Sub-phase C: ~6 tests (canonicalizer with built-in + user aliases)
- Sub-phase D: ~5 tests (env-var layering edge cases)
- Sub-phase E: 0 net new (test migration)
- Sub-phase F: ~5 tests (MCP tool + gateway error)
- Sub-phase G: 0 net new (script run pre-deploy, validates against live data)
- Sub-phase H: 0 (docs)

**Estimate**: ~36 new tests cumulative.

---

## 16. Acceptance gates

Plan ships when:

- [x] Registry primitives (§4) imported in `schema/__init__.py`.
- [x] All 4 schema files (§5) typecheck against new alias.
- [x] **R1+R2 — Schema snapshot tests regenerated and reviewed** (Codex R0 should-fix #1, R1 finding #1): four snapshots updated — `test_process_template_boundary.py:90`, `test_investment_idea_boundary.py:100`, `test_shared_slice_isomorphism.py:195` (`thesis_v1_0.schema.json`), `test_shared_slice_isomorphism.py:199` (`handoff_v1_1.schema.json`). Diff manually inspected for each to confirm only enum-removal is captured.
- [x] **R1 — Frontend dropdown is dynamic** (Codex R0 should-fix #2): `ResearchWorkspace.tsx`'s `STRATEGY_OPTIONS` fetches from `list_strategy_categories` MCP tool; verified end-to-end with at least one user-registered category visible in the UI.
- [x] **R1 — `list_strategy_categories` MCP tool registration test passes**: tool registered in `agents_mcp/server.py`, callable via gateway, returns `{categories: [{id, display_name, aliases, description, is_builtin}]}` shape.
- [x] **R1 — User-category accept/reject tests across all consumer contracts**: `InvestorProfile`, `InvestmentIdea`, `Thesis` each have explicit tests asserting (a) registered user category accepted, (b) unregistered string rejected with clear error message, (c) JSON round-trip preserves canonical ID.
- [x] **R1 — Permanent CI fixture tests** (Codex R0 should-fix #9): `tests/test_strategy_category_fixtures.py` covers loader edge cases — duplicate id, alias collision, built-in-redefinition, alias-equals-canonical-id, normalized variants of all built-in aliases.
- [x] Migration safety script (§10) runs clean in fixture-only fallback; optional live SQLite validation is available via `STRATEGY_CATEGORY_MIGRATION_DB`.
- [x] User-config layering (§7) works end-to-end with at least one user category (`growth`).
- [x] Plan #9's CI gate passes against registry-validated category list.
- [x] Master plan §6.5 + §12 updated; plan #9 §3.1 cross-reference added; `TODO.md` V2.P9f row marked SHIPPED.
- [x] Codex PASS R≥1 on this plan.

---

## 17. Codex review request

Send to Codex with:
- This file
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` (master, §6.5 specifically)
- `docs/planning/completed/KNOWLEDGE_WIKI_SCHEMA_PLAN.md` (plan #9 — coupled consumer)
- `docs/planning/completed/PROCESS_TEMPLATE_PLAN.md` (plan #5 source)
- `AI-excel-addin/schema/process_template.py`
- `AI-excel-addin/schema/investment_idea.py`
- `AI-excel-addin/schema/thesis_shared_slice.py`
- `AI-excel-addin/schema/enum_canonicalizers.py`

**Asks for Codex**:
1. Does keeping `StrategyBias` as an alias indefinitely cause confusion? Better to deprecate?
2. Should the registry carry per-category metadata (seed-factor defaults, valuation method defaults) or stay minimal? R0 says minimal.
3. Is YAML-on-disk the right registry storage, or should it be SQLite-backed for future user-authoring?
4. Live reload — really not needed? What's the ops cadence assumption?
5. Migration safety check — should it be a permanent pre-deploy CI gate or one-off?
6. Anything load-order-fragile about the singleton `STRATEGY_REGISTRY` import (e.g., circular imports through `enum_canonicalizers` → `process_template` → registry)?
7. Encourage local execution — actually instantiate `StrategyCategoryRegistry()` with `STRATEGY_CATEGORY_REGISTRY_PATH` set, register `growth`, build an `InvestmentIdea(strategy="growth")`, and round-trip JSON before approving.

---

## 18. Change log

- **R0** (2026-04-25) — Initial draft. Surfaced from plan #9 design discussion when user noted that "hardcoded 4 categories makes the system limited for others." Two-field design (plan #9) handles methodology-content taxonomy; this plan handles investor-style taxonomy. Both axes stay distinct. Awaiting first Codex round.
- **R1** (2026-04-25) — Codex R0 returned PASS-with-should-fixes (10 items). Fixes:
  - **Should-fix #1** (§5.4, §16): Acknowledged snapshot tests at `test_process_template_boundary.py:90` and `test_investment_idea_boundary.py:100` will need regeneration. Added snapshot-review acceptance gate.
  - **Should-fix #2** (§9.1, §9.3, §16): Named hand-maintained frontend files — `ResearchWorkspace.tsx` (`STRATEGY_OPTIONS` becomes dynamic), `AddFactorModal.tsx` (`STRATEGY_FACTOR_SUGGESTIONS` stays as built-in fallback). Added frontend-dropdown acceptance gate.
  - **Should-fix #3** (§4.2, §12.1 #7): Replaced ad-hoc `.replace(" ", "_").replace("-", "_")` with shared `_normalize()` using `re.sub(r"[\s\-_]+", "_", ...)` to match existing `enum_canonicalizers.py:21` semantics.
  - **Should-fix #4** (§4.2, §12.1 #8, §16): Added duplicate-id, alias collision, alias-equals-canonical-id checks at registry construction. Added permanent CI fixture tests acceptance gate.
  - **Should-fix #5** (§12.1 #3): `StrategyBias` alias kept indefinitely, no runtime warning. Documented in `SKILL_CONTRACT_MAP.md` as new code → `StrategyCategoryId`, legacy → `StrategyBias`.
  - **Should-fix #6** (§12.1 #9): Per-category metadata stays minimal (id, display_name, aliases, description). No `default_seed_factors` etc.
  - **Should-fix #7** (§12.2 closed): YAML + no live reload confirmed.
  - **Should-fix #8** (§9.2, §12.1 #10, §16): `list_strategy_categories` MCP tool returns `is_builtin` flag. Added MCP-tool-registration acceptance gate.
  - **Should-fix #9** (§10): Migration script stays pre-deploy gate; permanent CI test added at `tests/test_strategy_category_fixtures.py` for fixture-based regressions.
  - **Should-fix #10** (§16): Added 4 new acceptance gates — schema snapshot review, frontend dropdown, MCP registration, user-category accept/reject across consumer contracts.
  - Open questions narrowed (§12.2): R0's 6 questions all closed; remaining: tombstone enforcement strength, frontend `STRATEGY_FACTOR_SUGGESTIONS` post-#5b UX.
- **R2** (2026-04-25) — Codex R1 returned FAIL with 2 findings. Fixes:
  - **Finding #1** (§5.4, §16): Snapshot list extended from 2 to 4 — added `test_shared_slice_isomorphism.py:195` (thesis schema) and `:199` (handoff schema). `Thesis.strategy` and `HandoffArtifact.thesis.strategy` both go through the `StrategyValue` alias, so JSON-Schema regeneration affects them too. R1 only listed the InvestmentIdea + ProcessTemplate boundary tests; R2 covers all four pinned schemas.
  - **Finding #2** (§4.2): `_add()` refactored to validate fully before mutation. R1 inserted `_alias_to_id[_normalize(cat.id)] = cat.id` before checking whether that normalized form was already an alias of a different category — silent overwrite hole when category A had alias `event-driven` and category B had id `event_driven`. R2 builds `planned_alias_writes: dict[str, str]` locally, runs three checks (canonical-id-vs-existing-alias, alias-vs-existing-alias, alias-vs-existing-canonical-id, plus same-batch alias collision), and only commits to `_by_id`/`_alias_to_id` if all checks pass.
  - Both R1 open questions closed by Codex R1 review (tombstones, STRATEGY_FACTOR_SUGGESTIONS) — moved to §12.2 closed list.
- **R3** (2026-04-25) — Codex R2 returned FAIL with 1 finding. Fix:
  - **§4.2 same-batch alias dupe check**: R2 wrote `if normalized in planned_alias_writes and planned_alias_writes[normalized] != cat.id: raise`. The `!= cat.id` clause is a no-op for same-category duplicates because both planned writes hold `cat.id` — the check never fires. R3 uses presence-only `if normalized in planned_alias_writes: raise`, with branched error messages for "alias = own canonical id" vs "alias appears twice for this category". Now correctly rejects: (a) duplicate aliases on same category, (b) alias equal to category's own canonical id. Cross-category collision was already handled by the earlier `existing != cat.id` check on `_alias_to_id` and is unchanged.
- **R4** (2026-04-25) — Codex R3 returned FAIL with 1 finding. R3 over-rejected: the shipped defaults YAML has `id: value, aliases: [Value, VALUE, value-investing]` where `Value` normalizes to `value` (the canonical id). R3 rejected this as "alias equals own canonical id," but the right semantics is to allow it as an idempotent no-op write to `_alias_to_id["value"] = "value"`. Fix:
  - Replaced `planned_alias_writes: dict` with `seen_alias_normalized: set` tracking only alias-list internals.
  - Removed the "alias == own canonical" rejection branch.
  - Same-batch alias-list duplicate (typo case) still rejected via `if normalized in seen_alias_normalized`.
  - Commit phase writes canonical-id self-entry, then iterates aliases and writes each normalized form. Aliases that normalize to the canonical id overwrite with the same value — harmless.
  - Net effect: defaults YAML in §3.2 cleaned up to honor "aliases must be normalized-distinct from canonical id and from each other". Display-only variants (`Value` for id `value`) are accepted as input via the canonical-id self-entry in `_alias_to_id` — no need to list them as aliases. New convention documented in YAML comment.
  - **§3.2 YAML changes**: `value` aliases trimmed `[Value, VALUE, value-investing]` → `[value-investing]`; `special_situation` trimmed → `[special-situations]`; `macro` trimmed → `[]`; `compounder` trimmed → `[compounder-quality, quality-compounder]`. User-override examples (`growth`, `income`, `garp`, `event_driven`) similarly tightened.
  - **Loader behavior under R4**: `aliases: [Value, VALUE, value-investing]` would still raise (`Value` and `VALUE` are typo-style duplicates after normalization). `aliases: [value-investing]` loads cleanly. User input "Value" still canonicalizes to "value" because of the canonical-id self-entry; aliases only need to cover normalization-distinct forms.
- **R5** (2026-04-25) — Codex R4 returned FAIL with 2 findings. Fixes:
  - **Finding #1** (§4.2): R4 inserted `_normalize` / `_NORMALIZE_RE` AFTER the `_add()` method ended, leaving the remaining `StrategyCategoryRegistry` methods (`is_registered`, `canonicalize`, `all_ids`, `builtin_ids`, `get`) orphaned at module-level indentation — they would have been parsed as nested under `_normalize()`, raising `AttributeError` at runtime. R5 moves `_normalize` + `_NORMALIZE_RE` to module-level above the class definition (next to `_FROZEN` and `_ID_PATTERN`), so the class body stays continuous and all methods are properly nested.
  - **Finding #2** (§9.2 return shape): MCP tool example still showed `aliases: ["Value", "VALUE", "value-investing"]` for `value` and `["Growth"]` for `growth` — contradicts the new §3.2 convention. Updated example to match: `value` → `aliases: ["value-investing"]`, `growth` → `aliases: []`.
