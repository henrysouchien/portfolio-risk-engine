# Editorial Seeder Vocabulary Migration Plan

> **Status**: READY FOR IMPLEMENTATION — Codex PASS R2 (2026-04-16)
> **Item**: Phase 2E-7 (Lane C follow-up)
> **Source**: Codex Phase 2D review R3 finding #4
> **Est. effort**: 0.5 days
> **Risk**: Low (config strings only — no behavior change)

---

## 1. Problem

`core/overview_editorial/memory_seeder.py._deterministic_seed_from_summary()` still hardcodes the editorial vocabulary as string literals:

```python
# memory_seeder.py:80-87 (current)
lead_with = ["performance", "concentration"]
if top_holdings and float(top_holdings[0].get("weight_pct") or 0.0) >= 15:
    lead_with = ["concentration", "risk"]

seed = dict(base_memory)
preferences = dict(seed.get("editorial_preferences") or {})
preferences["lead_with"] = lead_with
preferences["care_about"] = list(dict.fromkeys([
    *(preferences.get("care_about") or []),
    "performance_vs_benchmark",
    "concentration",
]))
```

Every other editorial module in production — generators, policy, ranker — already imports vocabulary from `core/overview_editorial/vocabulary.py`. The seeder is the lone **production** holdout. (Test fixtures like `tests/core/overview_editorial/test_policy.py` and `tests/core/overview_editorial/eval_scenarios/*.json` also carry literal category/tag strings, but migrating those is out of scope — test fixtures being explicit about the concrete string is arguably the right thing.) If a canonical vocabulary string is ever renamed, the seeder silently drifts.

## 2. Semantic audit — what each string actually is

Looking at how `lead_with` / `care_about` are consumed (`policy.py:309-324` `_compute_memory_fit`):

```python
labels = {category, *tags}
if labels & lead_with: return 1.0
if labels & care_about: return 0.7
```

Both **category names** and **tags** are legal values for the preference lists. The four seeder literals split into two kinds:

| Literal | Kind | Already canonicalized? |
|---|---|---|
| `"performance"` | Category (matches `InsightCandidate.category` — see `generators/performance.py:25`) | ❌ not in `vocabulary.py` |
| `"risk"` | Category (matches `InsightCandidate.category` — see `generators/risk.py:25`) | ❌ not in `vocabulary.py` |
| `"concentration"` | Category AND a tag | ✅ `TAGS.CONCENTRATION` |
| `"performance_vs_benchmark"` | Tag only | ✅ `TAGS.PERFORMANCE_VS_BENCHMARK` |

Note: `TAGS.CONCENTRATION` happens to equal the category string because the concentration generator names overlap; this is coincidence, not semantic equivalence.

## 3. Architecture decision — new `CATEGORIES` namespace

**Decision**: Add a separate `CATEGORIES = SimpleNamespace(...)` to `vocabulary.py` rather than expanding `TAGS`.

**Why not expand TAGS**: `TAGS` currently holds values for `InsightCandidate.tags` (fine-grained labels on a candidate's content). Mixing category values in would blur the namespace semantic — TAGS would become a grab-bag of "any string that might show up in editorial_preferences." A dedicated `CATEGORIES` namespace keeps the vocabulary self-documenting.

**Why not leave `"performance"` / `"risk"` as string literals (partial migration)**: Defeats the purpose. Codex's finding is about single source of truth. Two string literals + two constants in the same function reads worse than all-string or all-constants.

**Why not migrate the generators at the same time**: Out of scope. Generator `name = "..."` and `category="..."` literals are coupled to the Generator protocol and to how `generators/__init__.py` registers them. That's a separate refactor (would touch ~7 generator files + their tests). Flagged as optional follow-up below.

## 4. Changes

### 4.1 `core/overview_editorial/vocabulary.py`

Add a new `CATEGORIES` namespace mirroring the 10-value `InsightCandidate.category` Literal in `models/overview_editorial.py:90-101`. Add to `__all__`. Complete coverage prevents the namespace from looking authoritative but omitting valid values.

```python
CATEGORIES = SimpleNamespace(
    CONCENTRATION="concentration",
    RISK="risk",
    PERFORMANCE="performance",
    LOSS_SCREENING="loss_screening",
    INCOME="income",
    TRADING="trading",
    FACTOR="factor",
    TAX="tax",
    EVENTS="events",
    PORTFOLIO_MIX="portfolio_mix",
)
```

**Invariant**: `CATEGORIES` values must match `InsightCandidate.category` Literal args 1:1. Add a structural test (§4.3 test 1) that enforces this — so a future change to either the model Literal or the namespace without updating the other fails a test. (Strictly speaking, the category vocabulary is dual-declared with the Pydantic Literal; `CATEGORIES` is the authoritative *namespace* for programmatic reference, guarded against drift by the structural test.)

Keep `TAGS.CONCENTRATION` as-is — it's legitimately used by the concentration generator's tag list (independent semantic from the category meaning). `TAGS.CONCENTRATION` and `CATEGORIES.CONCENTRATION` happen to equal the same string; that's coincidence, not duplication.

### 4.2 `core/overview_editorial/memory_seeder.py`

Swap the four literals:

```python
# line 80-87 (new)
from .vocabulary import CATEGORIES, TAGS

lead_with = [CATEGORIES.PERFORMANCE, CATEGORIES.CONCENTRATION]
if top_holdings and float(top_holdings[0].get("weight_pct") or 0.0) >= 15:
    lead_with = [CATEGORIES.CONCENTRATION, CATEGORIES.RISK]

seed = dict(base_memory)
preferences = dict(seed.get("editorial_preferences") or {})
preferences["lead_with"] = lead_with
preferences["care_about"] = list(dict.fromkeys([
    *(preferences.get("care_about") or []),
    TAGS.PERFORMANCE_VS_BENCHMARK,
    CATEGORIES.CONCENTRATION,
]))
```

Import placement: at the top of the module with the other `from .editorial_state_store import ...` imports.

### 4.3 Tests

**`tests/core/overview_editorial/test_vocabulary.py`** — add two tests:

**Test 1 — structural invariant between `CATEGORIES` and the `InsightCandidate.category` Literal.** If either drifts, this fails. This is what makes `CATEGORIES` authoritative rather than just a lookalike namespace.

```python
def test_categories_namespace_matches_insight_candidate_literal() -> None:
    import typing
    from core.overview_editorial.vocabulary import CATEGORIES
    from models.overview_editorial import InsightCandidate

    # Extract the Literal args from InsightCandidate.category annotation.
    category_field = InsightCandidate.model_fields["category"].annotation
    literal_values = set(typing.get_args(category_field))

    namespace_values = {v for k, v in vars(CATEGORIES).items() if not k.startswith("_")}
    assert namespace_values == literal_values
```

**Test 2 — smoke assertion on the three values the seeder reads** (makes it obvious from the test file what vocabulary powers the seeder):

```python
def test_categories_namespace_covers_seeder_values() -> None:
    from core.overview_editorial.vocabulary import CATEGORIES
    assert CATEGORIES.PERFORMANCE == "performance"
    assert CATEGORIES.RISK == "risk"
    assert CATEGORIES.CONCENTRATION == "concentration"
```

**`tests/core/overview_editorial/test_memory_seeder.py`** — add a **monkeypatch-sentinel test** that proves the seeder reads module constants at runtime, not equivalent string literals. This is the real invariant: if someone re-hardcodes `"performance"`, the sentinel won't flow through and the test fails.

```python
def test_deterministic_seed_reads_module_constants_not_literals(monkeypatch) -> None:
    from core.overview_editorial import memory_seeder
    from core.overview_editorial.vocabulary import CATEGORIES, TAGS

    # Swap canonical values to provably-distinct sentinels. If the seeder
    # reads the module constants, these sentinels appear in the output.
    # If anyone re-hardcodes "performance"/"risk"/"concentration" in
    # _deterministic_seed_from_summary, this test fails.
    monkeypatch.setattr(CATEGORIES, "PERFORMANCE", "__SENTINEL_CAT_PERF__")
    monkeypatch.setattr(CATEGORIES, "RISK", "__SENTINEL_CAT_RISK__")
    monkeypatch.setattr(CATEGORIES, "CONCENTRATION", "__SENTINEL_CAT_CONC__")
    monkeypatch.setattr(TAGS, "PERFORMANCE_VS_BENCHMARK", "__SENTINEL_TAG_PVB__")

    # Stub DB loader so this test doesn't require Postgres.
    monkeypatch.setattr(
        memory_seeder,
        "load_editorial_state",
        lambda user_id, _portfolio: ({"editorial_preferences": {}, "current_focus": {}}, None),
    )

    # Under-15% top holding → seeder uses PERFORMANCE + CONCENTRATION.
    summary_small = {
        "total_value": 100_000.0,
        "position_count": 5,
        "top_holdings": [
            {"ticker": "AAPL", "weight_pct": 10.0, "type": "equity"},
            {"ticker": "MSFT", "weight_pct": 8.0, "type": "equity"},
        ],
    }
    result = memory_seeder._deterministic_seed_from_summary(user_id=1, summary=summary_small)
    prefs = result["editorial_preferences"]
    assert prefs["lead_with"] == ["__SENTINEL_CAT_PERF__", "__SENTINEL_CAT_CONC__"]
    assert "__SENTINEL_TAG_PVB__" in prefs["care_about"]
    assert "__SENTINEL_CAT_CONC__" in prefs["care_about"]

    # ≥15% top holding → seeder uses CONCENTRATION + RISK.
    summary_large = {
        **summary_small,
        "top_holdings": [{"ticker": "AAPL", "weight_pct": 22.0, "type": "equity"}],
    }
    result = memory_seeder._deterministic_seed_from_summary(user_id=1, summary=summary_large)
    assert result["editorial_preferences"]["lead_with"] == [
        "__SENTINEL_CAT_CONC__",
        "__SENTINEL_CAT_RISK__",
    ]
```

Notes on the sentinel approach:
- `SimpleNamespace` attributes are mutable, so `monkeypatch.setattr(CATEGORIES, "PERFORMANCE", ...)` flips the value on the shared instance for the test's duration. `memory_seeder` imports `CATEGORIES` by reference, so both modules see the same instance.
- `EditorialMemory` model has `ConfigDict(extra="allow")` and `editorial_preferences: dict[str, Any]` — Pydantic does not constrain the string values, so sentinels pass validation cleanly.
- `load_editorial_state` is stubbed to avoid the DB dependency; existing `test_memory_seeder.py` uses the same pattern (see its fixture at line 20).

## 5. What is NOT changed

- Generator `name = "..."` and `category="..."` literals — out of scope.
- `TAGS` contents — not touched.
- `_compute_memory_fit` ranker logic — unchanged; still case-insensitive string-set intersection.
- `_llm_seed_from_summary()` — the LLM path generates vocabulary freely per the Pydantic schema; no vocabulary guardrail added (that's a different project).
- Other Phase 2E items — independent.

## 6. Verification

1. Run the editorial test suite: `pytest tests/core/overview_editorial/test_vocabulary.py tests/core/overview_editorial/test_memory_seeder.py -v`.
2. Run the full editorial suite to catch any import regressions: `pytest tests/core/overview_editorial/ -v`.
3. Smoke check: `python -c "from core.overview_editorial.vocabulary import CATEGORIES; print(CATEGORIES.PERFORMANCE, CATEGORIES.RISK, CATEGORIES.CONCENTRATION)"`.

No backend-server restart needed — this is pure Python module state.

## 7. Rollback

Trivial — revert the three file edits (`vocabulary.py`, `memory_seeder.py`, and the two test additions). No data migration, no schema change, no cache invalidation.

## 8. Optional follow-up (NOT this plan)

Migrate generator `name = "..."` and `category=` literals to `CATEGORIES.*` across `generators/performance.py`, `generators/risk.py`, `generators/concentration.py`, etc. Separate plan if/when someone picks it up. The value is lower there because each generator only names itself once, so drift risk is small.

## 9. Commit

Single commit. Suggested message:
```
refactor(editorial): migrate memory seeder to canonical vocabulary

Replace string literals in _deterministic_seed_from_summary() with
CATEGORIES + TAGS constants from core/overview_editorial/vocabulary.py.
Introduces a CATEGORIES SimpleNamespace for category-level preference
values (distinct from tag-level TAGS). Closes Codex Phase 2D R3 #4.

No behavior change.
```
