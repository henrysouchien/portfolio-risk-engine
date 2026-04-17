# Overview Editorial Pipeline — Phase 2D Implementation Plan: Editorial Memory Personalization

**Status**: DRAFT R5 — addressing R4 Codex findings
**Created**: 2026-04-13
**Updated**: 2026-04-14 (R5 — 2 R4 findings addressed: removed last "do NOT need changes" contradiction for MCP tool, fixed D2 test count 7→8)
**Inputs**:
- Design doc: `docs/planning/EDITORIAL_MEMORY_PERSONALIZATION_DESIGN.md` (R4c — Codex reviewed)
- Architecture spec: `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_ARCHITECTURE.md`
- Audit: `docs/planning/EDITORIAL_PIPELINE_AUDIT.md` (Gap 5: shallow editorial memory usage)
- Phase 1 plan pattern: `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md`

**Scope**: Five independently committable sub-phases (D1-D5) implementing the highest-value editorial memory personalization. The editorial memory has five sections but only `editorial_preferences` → score modifiers are used today. This plan wires the two most impactful sections (`editorial_preferences` via tags, `investor_profile.concerns` via anchoring) plus data-quality infrastructure for `current_focus`.

**What shipped vs what's deferred**: Codex review (R1, 20 findings) recommended a simpler cut: tags + memory_fit + anchored metrics + depth normalization. Threshold tuning, state detection, watchlist generator, and arbiter refinement are speculative behavior built on 3 generators with small candidate inventories. Defer until more generators exist (Phase 2A/2B) and telemetry shows what's needed.

**Relationship to other Phase 2 plans**:
- 2A (loss screening, events, benchmark): Independent. New generators benefit from tags (D3).
- 2B (generator expansion): Independent. New generators use vocabulary (D2).
- 2C (infrastructure): Independent.

**Estimated timeline**: ~9 working days (~2 weeks). Critical path: D1→D3→D5.

---

## 1. Sub-phase Summary

| # | Sub-phase | Scope | Duration | Depends on | Commits |
|---|---|---|---|---|---|
| D1 | Schema: `tags` on InsightCandidate | `models/overview_editorial.py` | ~1 day | — | 1 |
| D2 | Vocabulary module + depth normalization (read-path) | New `vocabulary.py` + seed file + state store | ~1.5 days | — | 1 |
| D3 | Generator tagging + enhanced `_compute_memory_fit()` | 3 generators + `policy.py` | ~2 days | D1, D2 | 1 |
| D4 | `current_focus` Pydantic submodels + store-layer normalization | Models + state store + seeder | ~2 days | D2 | 1 |
| D5 | Concern-to-metric resolver + anchored metrics | `policy.py` | ~2 days | D2, D3 | 1 |

**Total**: 5 commits, ~34 tests, ~9 working days

---

## 2. Dependency Graph

```
D1 (tags on InsightCandidate) ──┐
                                v
D2 (vocabulary + depth norm) ──> D3 (generator tagging + memory_fit) ──> D5 (anchored metrics)
  │                                                                        ^
  ├──> D4 (current_focus submodels + store normalization)                   │
  └────────────────────────────────────────────────────────────────────────┘
```

**Critical path**: D1+D2 → D3 → D5 (~6 days). D1 and D2 both feed D3; whichever finishes last gates D3.
**Parallelism**: D1 ∥ D2. D4 ∥ D3/D5.

---

## 3. Cross-Cutting Concerns

### 3.1 `_StrictModel` constraint
`InsightCandidate` uses `extra="forbid"` (`models/overview_editorial.py:11`). New fields MUST be declared explicitly. D1 (schema) must ship before D3 (tagging).

### 3.2 Vocabulary single source of truth
After D2+D3 ship, all **generator tags** flow from `vocabulary.py` constants. The memory seeder (`_deterministic_seed_from_summary()`) still hardcodes preference strings like `"performance"`, `"concentration"` when constructing `lead_with`/`care_about` lists — these are editorial memory values written for the user, not internal tags. Migrating the seeder to use `TAGS.*` constants is a cleanup that can ride along with D3 or D4 but is not blocking.

### 3.3 Backward compatibility
- `tags` defaults to `[]` — existing candidates score identically to today
- Enhanced `_compute_memory_fit()` preserves category-matching; tags are additive
- `current_focus` submodels accept old-shape `{ticker, weight_pct}` via optional fields

### 3.4 Normalization enforcement layer (Codex R1 finding #3)
`normalize_current_focus()` is called in the **store layer** (`set_editorial_memory()` and `seed_editorial_memory_if_missing()`) so no future caller can bypass it. `normalize_depth()` is called on the **read path** (`load_editorial_state()`) as a safety net for legacy data. Depth is NOT normalized on write in this phase — the seed file update to enum value is the primary write-source fix.

### 3.5 Synthesized leads inherit tags (Codex finding #4)
`compose_brief()` at `policy.py:87` manufactures a synthetic `InsightCandidate` when no lead_insight exists. D3 ensures this synthesized lead inherits `tags` from the source metric candidate it promotes from. Without this, memory_fit behavior would diverge between emitted and synthesized leads.

---

## 4. Sub-phase D1 — Schema: `tags` on InsightCandidate

### 4.1 Goal

Add optional `tags: list[str]` to `InsightCandidate` for cross-cutting vocabulary labels.

### 4.2 Files to modify

| File | Change |
|---|---|
| `models/overview_editorial.py` | Add `tags: list[str] = Field(default_factory=list)` after `category` (line ~89) |

### 4.3 Changes

```python
class InsightCandidate(_StrictModel):
    slot_type: Literal["metric", "lead_insight", "attention_item"]
    category: Literal[...]
    tags: list[str] = Field(default_factory=list)   # NEW
    content: dict[str, Any]
    ...
```

Default `[]` ensures all existing code that constructs `InsightCandidate` without `tags` continues to work.

### 4.4 Tests (3 tests)

1. `InsightCandidate` with explicit `tags=["risk_framework_gaps"]` validates and round-trips
2. `InsightCandidate` without `tags` kwarg validates with default `[]`
3. Serialization via `model_dump(mode="json")` includes `tags` field

### 4.5 Acceptance gate

- All existing generator/policy tests pass unchanged (they don't pass `tags`)
- `InsightCandidate.model_json_schema()` includes `tags`

### 4.6 Risks and rollback

- **Risk**: Test fixtures constructing `InsightCandidate` via explicit kwargs may break if they use positional args. Mitigated: all existing tests use keyword arguments (verified in `test_policy.py`).
- **Rollback**: Revert single commit. Field is optional with default — no data migration.

---

## 5. Sub-phase D2 — Vocabulary Module + Depth Normalization

### 5.1 Goal

Create canonical vocabulary with tag constants and depth normalization. Wire depth normalization into the read path (`load_editorial_state()`). This closes Codex R1 finding #1: legacy DB rows with prose depth values are normalized on read. The seed file is updated to use the enum value directly, so the primary write source produces clean data. Write-path enforcement (normalizing depth inside `set_editorial_memory()`) is deferred — the read-path normalization is the safety net for any legacy or malformed data.

### 5.2 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `core/overview_editorial/vocabulary.py` | Tag constants, depth normalization, concern-to-metric mapping | ~60 |
| `tests/core/overview_editorial/test_vocabulary.py` | Unit tests | ~80 |

### 5.3 Files to modify

| File | Change |
|---|---|
| `config/editorial_memory_seed.json` | `briefing_philosophy.depth`: prose → `"high_level"` |
| `core/overview_editorial/editorial_state_store.py` | `load_editorial_state()`: normalize `briefing_philosophy.depth` in returned memory dict before returning |

### 5.4 Key contents of `vocabulary.py`

```python
from types import SimpleNamespace

# Canonical tag vocabulary — generators import and use these.
# Same strings as editorial_memory.editorial_preferences lists.
TAGS = SimpleNamespace(
    RISK_FRAMEWORK_GAPS="risk_framework_gaps",
    CONCENTRATION="concentration",
    PERFORMANCE_VS_BENCHMARK="performance_vs_benchmark",
    INCOME_GENERATION="income_generation",
    UPCOMING_EVENTS="upcoming_events",
    EARNINGS_DATES="earnings_dates",
    DIVIDEND_DATES="dividend_dates",
    NEW_INFORMATION="new_information",
    DAILY_PNL_SWINGS="daily_pnl_swings",
    MOMENTUM_SIGNALS="momentum_signals",
    DETAILED_FACTOR_DECOMPOSITION="detailed_factor_decomposition",
    VARIANCE_ATTRIBUTION="variance_attribution",
)

# Depth normalization — simple enum check, no prose parsing
DEPTH_ENUM = frozenset({"summary", "high_level", "detailed"})
DEPTH_LEVELS: dict[str, int] = {"summary": 2, "high_level": 3, "detailed": 5}

def normalize_depth(raw: str | None) -> str:
    """Simple enum check. Unrecognized prose or non-string → 'high_level'."""
    if not raw or not isinstance(raw, str):
        return "high_level"
    text = raw.strip().lower().replace("-", "_")
    return text if text in DEPTH_ENUM else "high_level"

# Concern-to-metric anchor mapping (consumed by D5)
# NOTE (Codex R2 #4): "unintended_factor_exposure" → "volatility" is a loose proxy.
# The risk generator emits a generic volatility metric, not a factor-exposure metric.
# A dedicated factor_exposure metric (Phase 2B factor generator) would be better.
# Volatility is the best available strip-level proxy until then.
CONCERN_METRIC_ANCHORS: dict[str, list[str]] = {
    "concentration_risk": ["diversification"],
    "unintended_factor_exposure": ["volatility"],
}
MAX_ANCHORED_METRICS = 2
```

### 5.5 Read-path normalization (Codex finding #1)

In `editorial_state_store.py` `load_editorial_state()`, after loading the memory dict (line ~39-67), normalize depth before returning:

```python
from core.overview_editorial.vocabulary import normalize_depth

def load_editorial_state(user_id, portfolio_id):
    # ... existing load logic ...
    # Normalize depth on read (catches legacy prose in DB rows and seed file)
    philosophy = memory.get("briefing_philosophy")
    if isinstance(philosophy, dict) and "depth" in philosophy:
        philosophy["depth"] = normalize_depth(philosophy["depth"])
    return memory, previous_brief
```

This ensures ALL consumers (policy layer, arbiter, future code) see the normalized enum value regardless of data source.

### 5.6 Tests (8 tests)

1. `normalize_depth("high_level")` returns `"high_level"`
2. `normalize_depth("detailed")` returns `"detailed"`
3. `normalize_depth("summary")` returns `"summary"`
4. `normalize_depth("High-level takeaways. No full decomposition.")` returns `"high_level"` (unrecognized prose → default)
5. `normalize_depth(None)` returns `"high_level"`
6. `normalize_depth(42)` returns `"high_level"` (non-string → default)
7. `CONCERN_METRIC_ANCHORS["concentration_risk"]` == `["diversification"]`
8. `load_editorial_state()` returns normalized depth (mock DB row with prose depth → returns `"high_level"`)

### 5.7 Acceptance gate

- All vocabulary tests pass
- Seed file updated with enum value
- `load_editorial_state()` normalizes depth on read — both DB-sourced and seed-fallback paths
- No import cycles (vocabulary imports only `SimpleNamespace`)

### 5.8 Risks and rollback

- **Risk**: Adding an import in `editorial_state_store.py` from `vocabulary.py`. This is `core/` → `core/` which is allowed.
- **Rollback**: Revert commit. Seed file reverts to prose. State store reverts to raw pass-through.

---

## 6. Sub-phase D3 — Generator Tagging + Enhanced `_compute_memory_fit()`

### 6.1 Goal

Tag all candidates from existing generators with vocabulary constants. Update `_compute_memory_fit()` to match on `{category} | tags`. Fix synthesized lead fallback to inherit tags.

### 6.2 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/generators/concentration.py` | Import `TAGS`, add `tags=[TAGS.CONCENTRATION]` to all candidates |
| `core/overview_editorial/generators/risk.py` | Import `TAGS`, add `tags=[TAGS.RISK_FRAMEWORK_GAPS]` to violation/elevated candidates |
| `core/overview_editorial/generators/performance.py` | Import `TAGS`, add `tags=[TAGS.PERFORMANCE_VS_BENCHMARK]` to benchmark-relative candidates (return, beta, alpha, lead_insight). Sharpe: tag only if metric includes benchmark Sharpe in `context_label` (Codex R2 #6 — Sharpe is not inherently benchmark-relative). Max drawdown gets no tag. |
| `core/overview_editorial/policy.py` | Enhanced `_compute_memory_fit()` at line 243; fix synthesized lead at line 87 to inherit tags |

### 6.3 Enhanced `_compute_memory_fit()` (replaces `policy.py` lines 243-256)

```python
def _compute_memory_fit(self, candidate: InsightCandidate, memory: dict) -> float:
    preferences = memory.get("editorial_preferences", {})
    lead_with = {str(item).strip().lower() for item in preferences.get("lead_with", [])}
    care_about = {str(item).strip().lower() for item in preferences.get("care_about", [])}
    less_interested = {str(item).strip().lower() for item in preferences.get("less_interested_in", [])}

    category = candidate.category.strip().lower()
    tags = {t.strip().lower() for t in candidate.tags}
    all_labels = {category} | tags

    # Strongest match wins (design doc precedence)
    if all_labels & lead_with:      return 1.0
    if all_labels & less_interested: return 0.1
    if all_labels & care_about:      return 0.7
    return 0.3
```

**Precedence change**: `less_interested_in` checked before `care_about`. If a candidate matches both lists, suppression wins. `lead_with` still trumps everything. No immediate effect (seed has no overlap between lists), but correct for user-edited memory that may overlap.

### 6.4 Synthesized lead inherits tags (Codex finding #4)

At `policy.py:87`, the fallback lead synthesis constructs a new `InsightCandidate`. Add `tags` from the source metric:

```python
# line 87-110, inside the fallback:
top_metric = slots["metric"][0]
slots["lead_insight"] = [
    RankedCandidate(
        candidate=InsightCandidate(
            ...
            tags=list(top_metric.candidate.tags),  # NEW — inherit from source
            ...
        ),
        ...
    )
]
```

### 6.5 Tests (8 tests)

1. `_compute_memory_fit` with tag in `care_about` → 0.7 (`tags=["performance_vs_benchmark"]`)
2. `_compute_memory_fit` with tag in `lead_with` → 1.0 (`tags=["risk_framework_gaps"]`)
3. `_compute_memory_fit` with tag in `less_interested_in` → 0.1 (`tags=["daily_pnl_swings"]`)
4. Category `"risk"` in `care_about` + tag `"risk_framework_gaps"` in `lead_with` → 1.0 (strongest wins)
5. `less_interested_in` beats `care_about` when both match → 0.1
6. `tags=[]` → category-only matching (backward compat, identical to today)
7. Concentration generator emits candidates with `tags` containing `"concentration"`
8. Synthesized fallback lead inherits tags from source metric candidate

### 6.6 Acceptance gate

- All existing policy tests pass (unchanged behavior for `tags=[]`)
- Precedence: `lead_with` > `less_interested_in` > `care_about` > default
- Synthesized lead has same tags as its source metric

### 6.7 Risks and rollback

- **Risk**: `less_interested_in` > `care_about` precedence is a behavior change. No immediate effect since seed lists don't overlap. Tests cover overlap cases explicitly.
- **Rollback**: Revert commit. Tags default to `[]`, memory_fit reverts to category-only.

---

## 7. Sub-phase D4 — `current_focus` Pydantic Submodels + Store-Layer Normalization

### 7.1 Goal

Validated Pydantic submodels for `current_focus` entries. Normalization enforced in the **store layer** (`set_editorial_memory()` and `seed_editorial_memory_if_missing()`), not scattered across callers. This addresses Codex R1 findings #2 (lossy writes need logging) and #3 (wrong enforcement layer).

**Scope clarification (Codex R2 finding #5)**: D4 is **forward-only data hygiene**, not a migration. Existing malformed `current_focus` DB rows are NOT repaired on read. `EditorialMemory` remains a loose envelope (`extra="allow"`) and `load_editorial_state()` returns raw `current_focus` data as-is. After D4, all NEW writes produce validated data. Consumers that read `current_focus` (future D9 WatchlistInsightGenerator) should parse entries through `WatchEntry.model_validate()` with defensive error handling.

### 7.2 Files to modify

| File | Change |
|---|---|
| `models/overview_editorial.py` | Add `WatchEntry`, `RecentAction`, `UpcomingEvent` submodels |
| `core/overview_editorial/vocabulary.py` | Add `normalize_current_focus()` function |
| `core/overview_editorial/editorial_state_store.py` | Call `normalize_current_focus()` inside `set_editorial_memory()` and `seed_editorial_memory_if_missing()` before DB write; `set_editorial_memory()` returns the normalized memory dict |
| `mcp_tools/overview_editorial.py` | Return the normalized memory from `set_editorial_memory()` instead of the pre-normalization `validated.model_dump()` echo |

### 7.3 Submodels (in `models/overview_editorial.py`)

```python
from datetime import date as DateType

class WatchEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    added: DateType | None = None       # validated ISO date, optional for back-compat
    reason: str | None = None
    weight_pct: float | None = None     # legacy auto-seeder field

class RecentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    action: str
    date: DateType
    detail: str | None = None

class UpcomingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    date: DateType
```

### 7.4 Store-layer enforcement (Codex finding #3)

Normalization in `editorial_state_store.py`, NOT in MCP tool / seeder callers:

```python
from core.overview_editorial.vocabulary import normalize_current_focus

def set_editorial_memory(user_id, memory, source="chat_tool"):
    # Normalize current_focus before persisting
    if "current_focus" in memory:
        memory["current_focus"] = normalize_current_focus(memory["current_focus"])
    # ... existing upsert logic ...
    return memory  # NEW: return the normalized dict so callers can echo it

def seed_editorial_memory_if_missing(user_id, seed_memory, log_extra=None):
    # Normalize current_focus before persisting
    if "current_focus" in seed_memory:
        seed_memory["current_focus"] = normalize_current_focus(seed_memory["current_focus"])
    # ... existing insert logic ...
```

**MCP tool echo fix (Codex R2 finding #2)**: `update_editorial_memory()` in `mcp_tools/overview_editorial.py` currently returns `validated.model_dump(mode="json")` (pre-normalization echo). After D4, `set_editorial_memory()` returns the normalized memory dict. The MCP tool should echo that instead:

```python
# mcp_tools/overview_editorial.py — change at lines 32-36:
normalized = set_editorial_memory(user_id, validated.model_dump(mode="python"), source="chat_tool")
return {
    "status": "success",      # preserve existing status string
    "user_id": user_id,
    "memory": normalized,      # post-normalization dict, not pre-normalization validated.model_dump()
}
```

This ensures the caller sees exactly what was persisted, including any entries dropped by `normalize_current_focus()`. The response shape (`status`, `user_id`, `memory`) and status string (`"success"`) are preserved — only the `memory` value changes from pre-normalization to post-normalization.

This means the memory seeder (`memory_seeder.py`) does NOT need `normalize_current_focus()` calls — the store enforces normalization for ALL callers. The MCP tool (`mcp_tools/overview_editorial.py`) still needs a minor change to echo the normalized return value instead of the pre-normalization payload (see MCP echo fix above).

### 7.5 WARN logging for dropped entries (Codex finding #2)

`normalize_current_focus()` logs at WARN (not DEBUG) when entries are dropped:

```python
def normalize_current_focus(raw: dict) -> dict:
    # ... for each entry type:
    try:
        validated = WatchEntry.model_validate(entry)
        ...
    except Exception:
        _logger.warning("Dropped invalid watching entry: %s", entry, exc_info=True)
```

This makes lossy writes observable in logs.

### 7.6 Tests (8 tests)

1. `WatchEntry` validates full new-shape `{ticker: "VALE", added: "2026-04-10", reason: "thesis review"}`
2. `WatchEntry` validates legacy `{ticker: "DSU", weight_pct: 28.9}` (added/reason default None)
3. `WatchEntry` rejects bad date string
4. `RecentAction` validates complete entry; rejects missing `date`
5. `UpcomingEvent` validates correctly
6. `normalize_current_focus` drops invalid entries, keeps valid, returns JSON-serializable output
7. `set_editorial_memory()` normalizes `current_focus` before DB write (mock DB, verify normalized payload)
8. `seed_editorial_memory_if_missing()` normalizes `current_focus` before DB write

### 7.7 Acceptance gate

- All tests pass
- Existing memory seeder tests pass (seeder calls store, store normalizes)
- MCP tool tests pass (tool calls store, store normalizes)
- WARN log emitted for dropped entries
- Output of `normalize_current_focus()` is JSON-serializable (no `datetime.date` objects)

### 7.8 Risks and rollback

- **Risk**: `extra="forbid"` on submodels rejects unexpected fields from LLM output. `normalize_current_focus()` catches via try/except and drops with WARN log — acceptable.
- **Rollback**: Revert commit. Store reverts to raw JSON pass-through.

---

## 8. Sub-phase D5 — Concern-to-Metric Resolver + Anchored Metrics

### 8.1 Goal

Implement concern-based metric anchoring: up to 2 metrics from `investor_profile.concerns` are guaranteed on the strip, but still score-ordered for position.

**Design decision (Codex finding #7)**: Anchoring guarantees **presence**, not **position**. The design doc explicitly chose this: anchored metrics participate in the same score-ordered layout as competitive metrics. The alternative (pinning to specific positions) forces visual weight that may not match the portfolio state. If the `diversification` metric is the most important signal, it will naturally rank high; if it's not, pinning it to position 1 over a more urgent signal is worse UX.

### 8.2 Files to modify

| File | Change |
|---|---|
| `core/overview_editorial/policy.py` | Add `_resolve_anchored_metric_ids()` method; update `select_slots()` signature + logic; add `exclude_ids` param to `_select_ranked()` |

### 8.3 Changes

**New `_resolve_anchored_metric_ids()`**:

```python
from core.overview_editorial.vocabulary import CONCERN_METRIC_ANCHORS, MAX_ANCHORED_METRICS

def _resolve_anchored_metric_ids(self, editorial_memory: dict) -> list[str]:
    concerns = (editorial_memory.get("investor_profile") or {}).get("concerns", [])
    anchored_ids: list[str] = []
    for concern in concerns:
        for metric_id in CONCERN_METRIC_ANCHORS.get(concern, []):
            if metric_id not in anchored_ids:
                anchored_ids.append(metric_id)
            if len(anchored_ids) >= MAX_ANCHORED_METRICS:
                return anchored_ids
    return anchored_ids
```

**Updated `select_slots()`** (replaces `policy.py:123-130`):

`select_slots()` gains `editorial_memory` parameter (default `None` for backward compat):
1. Resolve anchored metric IDs from concerns
2. Pull anchored candidates from the ranked pool (match by `content["id"]`)
3. Fill remaining slots (6 − anchored count) competitively via `_select_ranked()` with `exclude_ids`
4. Merge all, sort by `composite_score` for position order

**Duplicate handling**: If the same metric ID appears in both anchored and competitive pools, `exclude_ids` in `_select_ranked()` prevents double-counting. The anchored version wins.

**Updated `_select_ranked()`**: gains optional `exclude_ids: set[str] | None = None`.

**Updated call site** (`compose_brief()` line 85):

```python
slots = self.select_slots(ranked_candidates, context.editorial_memory)
```

### 8.4 Tests (6 tests)

1. `_resolve_anchored_metric_ids` returns `["diversification"]` for `concerns=["concentration_risk"]`
2. Resolver returns `["diversification", "volatility"]` for both concerns
3. Resolver returns `[]` for unmapped concern (`position_sizing_drift`)
4. Resolver caps at `MAX_ANCHORED_METRICS` (2)
5. `select_slots` anchors `diversification` metric even when outscored by 6+ other metrics
6. `select_slots` with no editorial memory = current behavior (backward compat)

### 8.5 Acceptance gate

- All existing policy tests pass (default `editorial_memory=None`)
- Anchored metric appears on strip even when it would not have made top 6 competitively
- If a mapped metric candidate was NOT emitted by any generator, the anchor is skipped (no phantoms)

### 8.6 Risks and rollback

- **Risk**: `select_slots()` signature change. Mitigated: default `editorial_memory=None` preserves all existing callers.
- **Rollback**: Revert commit. `select_slots` reverts to purely competitive selection.

---

## 9. Implementation Schedule

**Week 1**:
- D1 (tags schema) — 1 day
- D2 (vocabulary + depth normalization + read-path) — 1.5 days, parallel with D1
- D3 (generator tagging + memory_fit + synthesized lead fix) — 2 days, after D1+D2

**Week 2**:
- D4 (current_focus submodels + store normalization) — 2 days, after D2, parallel with D5
- D5 (anchored metrics) — 2 days, after D3

**Total: ~9 working days (~2 weeks)**

---

## 10. QA Checklist

1. Load overview — verify `diversification` metric anchored on strip (from `concentration_risk` concern)
2. Verify `volatility` metric anchored (from `unintended_factor_exposure` concern)
3. Change `lead_with` to `["performance"]` via MCP tool — verify performance lead wins over concentration
4. Tag-based `_compute_memory_fit` returns 1.0 for `risk_framework_gaps` tag matching `lead_with`
5. Verify `load_editorial_state()` normalizes legacy prose depth to `"high_level"`
6. Populate `current_focus.watching` via MCP tool with invalid date — verify WARN log + entry dropped
7. Empty editorial memory → overview generates with all defaults
8. All existing tests pass (full pytest run)
9. No `fastapi`/`mcp_tools` imports in `core/overview_editorial/`

---

## 11. Deferred Items (Phase 2D.2 — after more generators ship)

| Item | Why deferred | Prerequisite |
|---|---|---|
| Memory-driven generator thresholds (concerns, risk_tolerance) | Codex: threshold collision rules undefined; speculative with 3 generators | Telemetry showing which thresholds matter |
| "System working" positive lead_insight | Codex: policy leak into generator; fix ranking instead | More lead candidates from 2A/2B generators |
| Depth-based annotation truncation | Only 3 generators emit ~3 annotations; cap rarely fires | Phase 2A/2B adding more generators/annotations |
| State detection (alert/default) + tiebreaker | Codex: double-counts urgency already in risk candidates | More candidate inventory to differentiate states |
| WatchlistInsightGenerator | Needs truncation (D7) to prevent annotation crowding | D4 (submodels) + annotation truncation |
| LLM arbiter refinement | Codex: marginal value; arbiter already has full memory blob | Structured output (Phase 2C) |
| `time_horizon` → novelty weight modulation | Dynamic scoring weight change; needs telemetry first | Observation of scoring patterns |
| `one_thing_that_matters` arbiter output | New schema field + frontend rendering | Phase 2C/3 |

---

## 12. Codex Review Log

**R1 (2026-04-13):** 20 findings (4 high, 8 medium, 4 low, 4 meta).

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | D2/D7 depth read-path contradiction — `load_editorial_state()` never normalizes | High | ACCEPTED. Read-path normalization moved into D2 (in `load_editorial_state()`). D7 removed. |
| 2 | D4 lossy writes are a new failure mode — silent entry dropping | High | ACCEPTED. WARN logging added for dropped entries in `normalize_current_focus()`. |
| 3 | D4 normalization at wrong layer — callers can bypass | High | ACCEPTED. Normalization moved to store layer (`set_editorial_memory()` / `seed_editorial_memory_if_missing()`). MCP tool and seeder no longer need `normalize_current_focus()` calls. MCP tool still needs a minor change to echo the normalized return value (R2 finding #2). |
| 4 | D3 synthesized leads don't inherit tags | High | ACCEPTED. Fallback lead synthesis at `policy.py:87` now inherits tags from source metric. |
| 5 | D6 threshold collision (concern vs risk_tolerance) | Medium | DEFERRED. D6 removed from scope. |
| 6 | D8 double-counts urgency | Medium | DEFERRED. D8 removed from scope. |
| 7 | D5 score-ordered anchoring weakens guarantee | Medium | NOTED. Design doc decision — presence not position. Documented in D5 as explicit design choice. |
| 8 | D6 "system working" is policy leak into generator | Medium | DEFERRED. D6 removed from scope. |
| 9 | D7 alphabetical tie-break is arbitrary | Medium | DEFERRED. D7 removed from scope. |
| 10 | D8 incoherent output on generator failure | Medium | DEFERRED. D8 removed from scope. |
| 11 | D9 depends on D7 (annotation truncation) | Medium | DEFERRED. D9 removed from scope. |
| 12 | D10 marginal value — arbiter already has full memory | Medium | DEFERRED. D10 removed from scope. |
| 13 | D9 positions snapshot contract unverified | Low | DEFERRED. D9 removed from scope. |
| 14 | D9 clock source (today vs context.generated_at) | Low | DEFERRED. D9 removed from scope. |
| 15 | Test count is a guess | Low | ACCEPTED. Revised to dependency-aware estimate (~32 tests). |
| 16 | Scope overstated (conversation_extracts LLM-only) | Low | ACCEPTED. Scope statement revised to reflect what ships. |
| 17-20 | Meta: over-engineered; simpler cut recommended | — | ACCEPTED. Scope reduced from 10 to 5 sub-phases. Speculative behavior deferred. |

**R2 (2026-04-13):** 6 findings (0 high, 4 medium, 2 low).

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | D5 dependency graph wrong — imports from `vocabulary.py` (D2) | Medium | ACCEPTED. D5 depends on D2+D3. Dependency graph and critical path updated. |
| 2 | MCP tool returns stale pre-normalization echo | Medium | ACCEPTED. `set_editorial_memory()` returns normalized dict; MCP tool echoes it. |
| 3 | D2 claims write+read normalization but only implements read | Medium | ACCEPTED. D2 goal text corrected to "read-path normalization." Seed file update is the write-source fix. |
| 4 | `unintended_factor_exposure → volatility` anchor loosely justified | Medium | NOTED. Comment added to `CONCERN_METRIC_ANCHORS`. Phase 2B factor generator provides better anchor. |
| 5 | D4 is forward-only, not a migration — plan should say so | Low | ACCEPTED. Explicit scope clarification added to D4 goal. |
| 6 | Sharpe tagged as `performance_vs_benchmark` is semantically wrong | Low | ACCEPTED. Sharpe tagged conditionally (only if benchmark Sharpe in context_label). |

**R3 (2026-04-14):** 4 findings (0 high, 3 medium, 1 low).

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | D2 summary row + cross-cutting still say "write + read" but D2 body defers write | Medium | ACCEPTED. Summary row and §3.4 text corrected to "read-path only." |
| 2 | MCP echo snippet uses wrong status string (`"ok"` vs `"success"`) and JSON-string vs dict; contradicts "no MCP changes" claim | Medium | ACCEPTED. Snippet corrected to preserve `"status": "success"` and dict `memory` shape. R1 log entry clarified. |
| 3 | `normalize_depth()` needs `isinstance(raw, str)` guard for non-string DB values | Medium | ACCEPTED. Guard added. Test for `normalize_depth(42)` added. |
| 4 | Seeder still hardcodes preference strings — "single source of truth" claim is false | Low | ACCEPTED. Claim scoped to generator tags only. Seeder migration noted as optional cleanup. |

**R4 (2026-04-14):** 2 findings (0 high, 1 medium, 1 low).

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | D4 §7.4 still says MCP tool "do NOT need changes" directly after prescribing the echo change | Medium | ACCEPTED. Text corrected: seeder doesn't need changes; MCP tool needs echo fix (already in D4 file list + snippet). |
| 2 | D2 test count says 7 but enumerates 8 items | Low | ACCEPTED. Count corrected to 8. |
