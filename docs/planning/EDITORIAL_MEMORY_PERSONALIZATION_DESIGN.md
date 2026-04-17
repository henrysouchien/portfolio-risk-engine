# Editorial Memory Personalization — Design Sketch

**Created:** 2026-04-13
**Updated:** 2026-04-13 (R4c — multiple Codex review rounds)
**Status:** SKETCH R4c — Codex reviewed, substance clean, ready for implementation planning
**Depends on:** Phase 1 editorial pipeline (shipped), editorial memory infrastructure (shipped)
**Related:** `EDITORIAL_PIPELINE_AUDIT.md` (Gap 5: shallow editorial memory usage)

## Purpose

The editorial memory (`config/editorial_memory_seed.json`, stored in `user_editorial_state` DB table) has five sections. The pipeline currently uses one (`editorial_preferences` → score modifiers in `_compute_memory_fit()`). This design specifies how each section should influence the overview's persistent surface — which metrics are always-on, which attention cards surface, how the lead insight is framed, and what the LLM arbiter should know.

The goal is not to replicate the chat briefing. The goal is to make the overview feel like *your* overview — the metrics, attention cards, and annotations reflect your concerns, goals, and what you're actively tracking.

## Current State

**Infrastructure in place:**
- `PortfolioContext.editorial_memory` is a full `dict[str, Any]` — the entire seed JSON is loaded and available to every generator and the policy layer
- `_compute_memory_fit()` reads `editorial_preferences` (lead_with, care_about, less_interested_in) and matches on `candidate.category`
- Memory fit is 25% of the composite score (`0.35 * relevance + 0.25 * urgency + 0.25 * memory_fit + 0.15 * novelty`)
- Every generator receives the full `PortfolioContext` but none read editorial memory directly
- The LLM arbiter receives the full editorial memory via `_build_prompt()` but is limited to rewriting 3 string fields (headline, evidence, selection_reasons)

**Editorial memory sections (from seed):**
```json
{
  "investor_profile": {
    "style": "value_investor",
    "risk_tolerance": "moderate",
    "time_horizon": "long_term",
    "experience_level": "professional",
    "primary_goals": ["capital_appreciation", "dividend_income"],
    "concerns": ["concentration_risk", "unintended_factor_exposure", "position_sizing_drift"]
  },
  "editorial_preferences": {
    "lead_with": ["risk_framework_gaps", "concentration"],
    "care_about": ["performance_vs_benchmark", "income_generation", "upcoming_events", ...],
    "less_interested_in": ["daily_pnl_swings", "momentum_signals", ...],
    "sophistication": "high"
  },
  "briefing_philosophy": {
    "default_state": "Show performance vs benchmark and income progress.",
    "alert_state": "Lead with what broke the risk framework.",
    "tone": "Analyst briefing, not dashboard.",
    "depth": "High-level takeaways. No full decomposition."
  },
  "current_focus": {
    "watching": [],
    "recent_actions": [],
    "upcoming": []
  },
  "conversation_extracts": [...]
}
```

---

## Section 1: `investor_profile`

### `concerns` — What keeps this user up at night

**How it should influence the persistent surface:**

#### Anchored metrics (max 2)

Concerns should drive which metrics are *anchored* — guaranteed to appear on the strip, but still score-ordered for position. Capped at 2 anchors to leave 4 competitive slots.

| Concern | Anchored metric | Why | Notes |
|---|---|---|---|
| `concentration_risk` | `diversification` (HHI + position count) | The user needs to see concentration at a glance every time. | The concentration generator currently emits only `diversification` as a metric (id `"diversification"`, HHI-based). It does NOT emit a `concentration` (top holding %) metric — that would need a new candidate if desired. For anchoring, `diversification` is sufficient. |
| `unintended_factor_exposure` | `volatility` | Factor variance and risk drivers are attention-item signals, not metric-strip material. Volatility is the compact strip-level proxy. | `factor_variance_pct` and `risk_drivers` from the risk snapshot should drive attention items and margin annotations (lowered thresholds), not metric pinning. Beta measures market sensitivity, which is related but not the same as unintended factor exposure. |
| `position_sizing_drift` | No metric — drives attention items | Drift is a per-position problem. | **Prerequisite:** drift detection requires baseline/target weights, which don't exist in the current positions snapshot. Deferred until drift data is available. |

**Implementation approach:** Centralize the concern-to-metric mapping in a single resolver function with tests (not scattered across generators). The resolver maps concern strings to metric candidate IDs. `select_slots()` checks this resolver, anchors up to 2 matching metric candidates from the existing pool, then fills the remaining slots competitively. If a mapped metric candidate doesn't exist in the pool (wasn't emitted by any generator), the anchor is skipped — no phantom candidates.

```python
# Centralized, testable, one place to update
CONCERN_METRIC_ANCHORS: dict[str, list[str]] = {
    "concentration_risk": ["diversification"],  # only candidate that exists today
    "unintended_factor_exposure": ["volatility"],
    # "position_sizing_drift" — no metric; drives attention items only
}
```

#### Lowered attention thresholds

| Concern | Threshold change | Prerequisite |
|---|---|---|
| `concentration_risk` | Concentration attention card threshold drops from 15% to 10% top weight | None — generator has the data |
| `unintended_factor_exposure` | Factor variance > 60% (instead of 70%) triggers a margin annotation | None — risk snapshot has `factor_variance_pct` |
| `position_sizing_drift` | Positions that have moved > 5 pts from initial weight get flagged | **Needs drift baselines** — not available today |

### `primary_goals` — What success looks like

| Goal | Persistent surface behavior |
|---|---|
| `capital_appreciation` | Return and Alpha are core success metrics. Performance generator emits a positive-tone lead_insight candidate when return > 0 and alpha > 0 — a "system is working" signal for default-state days. |
| `dividend_income` | Needs income generator (Phase 2). Until then, no deterministic behavior. |

### `time_horizon` — How much noise to filter

**Codex review flagged this as the biggest omission.**

| Time horizon | Behavior |
|---|---|
| `long_term` | Suppress daily PnL swings (aligns with `less_interested_in: ["daily_pnl_swings"]`). Extend event windows (30-day lookahead vs 7-day). Weight novelty scoring lower — things don't need to be "new" to matter for a long-term investor. |
| `short_term` | Daily moves are relevant. Shorter event windows. Higher novelty weight. |

**Implementation approach:** `time_horizon` feeds into generator threshold adjustments (similar to concerns) and could modulate the novelty weight in `rank()`.

### `risk_tolerance` — Threshold calibration

| Tolerance | Behavior |
|---|---|
| `moderate` | Current thresholds are calibrated for this. |
| `aggressive` | Raise attention card thresholds (concentration warning at 25% not 15%, volatility warning at 25% not 20%). |
| `conservative` | Lower thresholds further (concentration at 10%, volatility at 15%). |

**Implementation approach:** Generators read `risk_tolerance` and scale their hardcoded thresholds. Straightforward multiplier pattern.

### `sophistication` / `experience_level` — Depth of explanation

These influence the LLM arbiter's tone and the `depth` behavior, not the deterministic layer's candidate selection. A professional expects terse analyst copy; a beginner needs more context. Handled in Section 4 (`briefing_philosophy`).

---

## Section 2: `editorial_preferences` (enhanced)

**Current state:** `_compute_memory_fit()` matches `candidate.category` against `lead_with`, `care_about`, and `less_interested_in`. Returns 1.0 / 0.7 / 0.1 / 0.3 (default).

**Problem:** Some `care_about` / `less_interested_in` items aren't generator categories — they're cross-cutting concerns. Adding generator-specific if-statements for each one will sprawl. (Codex review: "Add candidate tags or semantic IDs before expanding memory behavior.")

### Candidate tags + preference vocabulary (prerequisite)

**R2 finding (High):** The design mixed user-facing preference strings (`performance_vs_benchmark`), generator categories (`risk`), and internal tag names (`benchmark_relative`) with no normalization between them. `_compute_memory_fit()` does exact-string matching against the memory seed's preference lists. Tags won't match preferences unless they use the same strings.

**Resolution:** One canonical vocabulary, used everywhere. Generators tag candidates with the *same strings* the user writes in `care_about` / `less_interested_in`. No separate internal tag namespace. The preference list IS the vocabulary.

Add an optional `tags: list[str] = []` field to `InsightCandidate`:

```python
InsightCandidate(
    slot_type="metric",
    category="performance",
    tags=["performance_vs_benchmark"],  # same string as in care_about
    content={...},
    ...
)
```

`_compute_memory_fit()` matches on `category` first (existing behavior), then checks `tags` for any overlap with preference lists:

```python
def _compute_memory_fit(self, candidate, memory):
    preferences = memory.get("editorial_preferences", {})
    lead_with = {s.strip().lower() for s in preferences.get("lead_with", [])}
    care_about = {s.strip().lower() for s in preferences.get("care_about", [])}
    less_interested = {s.strip().lower() for s in preferences.get("less_interested_in", [])}
    
    category = candidate.category.strip().lower()
    tags = {t.strip().lower() for t in candidate.tags}
    all_labels = {category} | tags
    
    # Strongest match wins
    if all_labels & lead_with:
        return 1.0
    if all_labels & less_interested:
        return 0.1
    if all_labels & care_about:
        return 0.7
    return 0.3
```

Vocabulary table — generators use these exact strings as tags:

| Tag (= preference string) | Which generators use it | User-facing preference list |
|---|---|---|
| `risk_framework_gaps` | Risk generator (limit violations, elevated volatility) | `lead_with` |
| `concentration` | Concentration generator (all candidates) | `lead_with` |
| `performance_vs_benchmark` | Performance generator (return vs benchmark, alpha) | `care_about` |
| `income_generation` | Income generator (when built) | `care_about` |
| `upcoming_events` | Events generator (when built) | `care_about` |
| `earnings_dates` | Events generator (when built) | `care_about` |
| `dividend_dates` | Events/Income generator (when built) | `care_about` |
| `new_information` | Any generator detecting changes | `care_about` |
| `daily_pnl_swings` | Performance generator (day-change candidates) | `less_interested_in` |
| `momentum_signals` | Future generators | `less_interested_in` |
| `detailed_factor_decomposition` | Factor generator (when built) | `less_interested_in` |
| `variance_attribution` | Risk generator (factor variance detail) | `less_interested_in` |

**Shared constant** in a common module (e.g., `core/overview_editorial/vocabulary.py`):

```python
# Canonical tag vocabulary — generators import and use these.
# Matches the strings in editorial_memory.editorial_preferences.
TAGS = SimpleNamespace(
    RISK_FRAMEWORK_GAPS="risk_framework_gaps",
    CONCENTRATION="concentration",
    PERFORMANCE_VS_BENCHMARK="performance_vs_benchmark",
    INCOME_GENERATION="income_generation",
    UPCOMING_EVENTS="upcoming_events",
    DAILY_PNL_SWINGS="daily_pnl_swings",
    MOMENTUM_SIGNALS="momentum_signals",
    # ... extend as generators are added
)
```

**Implementation approach:**
1. Add `tags: list[str] = []` to `InsightCandidate` model
2. Create `core/overview_editorial/vocabulary.py` with shared constants
3. Generators tag candidates at emission time using vocabulary constants
4. `_compute_memory_fit()` checks `{category} | tags` against preference lists (single match path)

---

## Section 3: `briefing_philosophy`

### `alert_state` / `default_state` — State detection

**Codex review:** With only 3 generators, an alert boost mostly double-counts urgency already baked into risk/concentration candidates. State detection should ship *after* candidate/schema enrichment, not before.

**Revised approach:** State detection is a policy-layer input, not a Phase A priority. Defer to after generators have richer candidates (Phase B work). When implemented:

```
ALERT if:
  - risk limit violations > 0 (from risk snapshot, structured signal)
  - any attention_item candidate has urgency == "alert"
DEFAULT otherwise
```

State flag goes into `EditorialMetadata` for the frontend (visual treatment) and LLM arbiter (framing). The deterministic layer uses it as a tiebreaker boost, not a primary scoring mechanism.

### `tone` — LLM arbiter only

"Analyst briefing, not dashboard." Passed to the arbiter prompt verbatim along with `experience_level` and `sophistication`.

### `depth` — Needs normalization + annotation enforcement

**R1 review:** Seed stores prose, not an enum.
**R2 review:** Even with normalization, annotations are deduped but never ranked or truncated today. `_dedupe_annotations()` passes all unique annotations through to the brief. There's no enforcement path for a depth cap.

**Proposed normalization:**
```python
DEPTH_LEVELS = {
    "summary": 2,      # max 2 annotations, terse lead
    "high_level": 3,    # max 3 annotations (current default)
    "detailed": 5,      # max 5 annotations, richer lead
}
```

**Normalization coverage — all paths:**

A shared `normalize_depth(raw: str | None) -> str` function validates depth values against a known enum. No prose parsing — unrecognized values fall back to `"high_level"`:

```python
# Known enum values — the only values that should be stored.
DEPTH_ENUM = {"summary", "high_level", "detailed"}

def normalize_depth(raw: str | None) -> str:
    if not raw:
        return "high_level"
    text = raw.strip().lower().replace("-", "_")
    if text in DEPTH_ENUM:
        return text
    # Unrecognized prose → default. Don't try to parse natural language.
    return "high_level"
```

**Strategy:** Don't parse prose. Instead, ensure all write paths produce enum values:
1. Update `config/editorial_memory_seed.json` to use `"high_level"` instead of prose
2. All three write paths (MCP tool, deterministic seeder, LLM seeder) write enum values
3. LLM seeder prompt constrains output to one of `summary | high_level | detailed`
4. Read-time: if value is not in enum (legacy DB row with prose), fall back to `"high_level"`

This eliminates the prose-parsing problem entirely. The function is a simple enum check with a safe default.

This function is called at:

**Write paths** (produce enum values):
1. `update_editorial_memory()` — normalizes on write
2. `memory_seeder.py` (deterministic + LLM) — normalizes before persisting

**Read path** (catches legacy prose in DB rows or seed file):
3. `load_editorial_state()` in `editorial_state_store.py` — normalizes depth in the returned `editorial_memory` dict before returning to callers. This is the shared read path used by both the policy layer (`compose_brief()`) and the LLM arbiter (via `PortfolioContext.editorial_memory`). Normalizing here ensures both consumers see the enum value, not prose.

The seed file itself (`config/editorial_memory_seed.json`) is updated to use the enum value `"high_level"` instead of prose. The read-path normalization is a safety net for any legacy data that predates the write-path enforcement.

**Annotation truncation:** After deduplication, annotations need a priority-based truncation step. Two options:

**(a) Score annotations like candidates** — add `relevance_score` to `MarginAnnotation`, generators assign scores, policy layer ranks and truncates to the depth cap. This is consistent with the metric/attention selection pattern but adds weight to the annotation model.

**(b) Simple type-priority truncation** — annotations are ordered by type (`ask_about` > `editorial_note` > `context`), then truncated to the depth cap. No scoring needed. Lighter, and annotations are already a small set (typically 3-5 from 3 generators).

**Decision:** Option (b) with a within-type tie-break. Annotations are a small pool; full scoring is overkill. But if cap is 2 and there are 3 `ask_about` annotations (one from each generator), we need a deterministic rule for which one gets dropped.

**Truncation rules:**
1. Sort by type priority: `ask_about` > `editorial_note` > `context`
2. Within the same type, sort by `anchor_id` alphabetically as a stable, deterministic tie-break
3. Truncate to depth cap

`MarginAnnotation` currently carries no source/generator metadata, so sorting by "which generator produced it" is not possible without a schema addition. `anchor_id` is already present on every annotation (e.g., `"lead_insight"`, `"artifact.concentration"`) and provides a stable, content-based ordering that doesn't depend on generator execution order.

If personalized priority is desired later (e.g., annotations from `lead_with` categories survive the cap), add an optional `source_category: str` field to `MarginAnnotation` at that point. For now, type + `anchor_id` is sufficient for the small annotation pool.

**Implementation:** Add `_truncate_annotations(annotations, depth_cap)` step in `compose_brief()` after deduplication, before brief assembly.

---

## Section 4: `current_focus`

**R1 review:** This section is not implementable with current data contracts.
**R2 review:** Migration is under-scoped — the auto-seeder already writes `watching` with `{ticker, weight_pct}` objects, a different shape than proposed.

### Current state of `current_focus` data

The auto-seeder (`memory_seeder.py:86-93`) writes `watching` as:
```json
{"watching": [{"ticker": "DSU", "weight_pct": 28.9}, ...]}
```

The editorial memory seed (`config/editorial_memory_seed.json`) has empty arrays. `update_editorial_memory()` validates only the top-level envelope (loose `EditorialMemory` model), not the shape of `current_focus` entries.

### Data prerequisites (must ship first)

**Target schema:**
```json
{
  "current_focus": {
    "watching": [
      {"ticker": "VALE", "added": "2026-04-10", "reason": "thesis review"}
    ],
    "recent_actions": [
      {"ticker": "DSU", "action": "trim", "date": "2026-04-10", "detail": "trimmed by 5%"}
    ],
    "upcoming": [
      {"label": "Q1 review", "date": "2026-04-30"}
    ]
  }
}
```

**Migration/back-compat plan:**
1. **Define Pydantic submodels** for `current_focus` entries with validated date fields:
   ```python
   from datetime import date as DateType
   from pydantic import field_validator
   
   class WatchEntry(BaseModel):
       ticker: str
       added: DateType | None = None       # validated ISO date, optional for back-compat
       reason: str | None = None
       weight_pct: float | None = None     # legacy field from auto-seeder, read-only
   
   class RecentAction(BaseModel):
       ticker: str
       action: str                         # "trim", "sell", "buy", etc.
       date: DateType                      # validated ISO date, required
       detail: str | None = None
   
   class UpcomingEvent(BaseModel):
       label: str
       date: DateType                      # validated ISO date, required
   ```
   Using `datetime.date` instead of `str` ensures malformed date strings are rejected at write time, not silently stored. Phase 4 readers can rely on valid dates without defensive parsing.
2. **Shared normalization function:** A single `normalize_current_focus(raw: dict) -> dict` function validates and normalizes `current_focus` entries through the submodels. Invalid entries (bad dates, missing required fields) are logged and dropped. This function is called by ALL write paths:
   - `update_editorial_memory()` (MCP tool — user/AI writes)
   - `memory_seeder.py` deterministic seeder (auto-seed on first connection)
   - `memory_seeder.py` LLM seeder (AI-generated seed from portfolio summary)
   
   No write path persists `current_focus` data without going through `normalize_current_focus()`.
   
   **Serialization:** `normalize_current_focus()` returns a JSON-serializable dict (not Pydantic objects). Validated `datetime.date` fields are serialized to ISO strings (`date.isoformat()`) before returning, so the output is safe for `json.dumps()` / JSONB persistence. The submodels are validation-only — they parse the input, validate types, and the normalizer converts back to plain dicts with string dates for storage.
3. **Auto-seeder updated** to construct `WatchEntry` objects directly (add `added` timestamp, keep `weight_pct` as optional legacy). Passes through `normalize_current_focus()` before persisting.
4. **LLM auto-seeder** output passes through `normalize_current_focus()` after `json.loads()` — prompt shaping is not equivalent to validation. The prompt includes the target schema as an example, but the normalizer is the enforcement point.
5. **Readers use the submodels** — Phase 4 generators parse `watching` entries through `WatchEntry.model_validate()` with `strict=False`. Old-shape entries with `{ticker, weight_pct}` pass validation (both fields are in the model). Missing `added`/`reason` fields default to `None`.
6. Existing DB rows with old-shape entries continue to work — the submodel is additive, not breaking.

### `watching` — Ticker-level annotations (after prerequisites)

When populated with structured entries, watched tickers surface as margin annotations:
- If the ticker is in the portfolio → annotation with current weight and return from positions snapshot
- If not in portfolio → deferred (requires external quote, adds data dependency)

**Implementation:** New `WatchlistInsightGenerator` that reads `current_focus.watching` from editorial memory + positions snapshot. Emits `MarginAnnotation` objects via `GeneratorOutput.annotations` (not through slot selection — annotations bypass ranking and go directly into the brief after deduplication).

### `recent_actions` — Exit ramp suppression: DESCOPED

**R2 finding (Medium):** `ExitRamp.payload` is an opaque string (`"holdings"`, `"scenario:rebalance"`, or a chat prompt). There's no structured ticker reference in the payload. Matching recent actions against exit ramps requires either:
- (a) Adding a structured `target_ticker` field to `ExitRamp` — schema change that ripples across all generators and the frontend
- (b) Regex/heuristic matching on payload strings — fragile

**Decision:** Descope from this design. Exit ramp suppression is a nice-to-have that requires an `ExitRamp` schema change to do properly. If it becomes a priority, design it as a standalone schema evolution — not as part of editorial memory personalization.

`recent_actions` data is still useful for the LLM arbiter (context for judgment: "user just trimmed DSU, don't suggest trimming again"). No deterministic behavior needed.

### `upcoming` — User-defined events (after prerequisites)

Structured entries with `date` field emit `attention_item` candidates with countdown. Part of the events generator when it ships, or a standalone `UserEventsInsightGenerator` if events generator is not yet available.

---

## Section 5: `conversation_extracts`

**Layer:** LLM arbiter only. The deterministic layer cannot use natural language context.

**Behavior:** The arbiter prompt includes the extracts for judgment context:
- "Doesn't check portfolio daily — 'is anything on fire' not 'how did I do today'" → Don't lead with small daily moves
- "Big moves = failure of risk framework" → Frame large drawdowns as framework failures, not market events

**Implementation:** The arbiter's `_build_prompt()` already serializes `editorial_memory` into the prompt JSON. The extracts are included in that serialization. No change needed for delivery — the limitation is what the arbiter is *allowed to change* (currently 3 string fields), not what it sees.

---

## Layer Summary

| Memory section | Deterministic layer | LLM arbiter |
|---|---|---|
| `investor_profile.concerns` | Anchored metrics (max 2) + lowered attention thresholds | Context for framing |
| `investor_profile.primary_goals` | "System working" lead_insight candidates | Success framing in default state |
| `investor_profile.time_horizon` | Noise suppression, event window length, novelty weight | N/A |
| `investor_profile.risk_tolerance` | Threshold scaling on generators | N/A |
| `investor_profile.sophistication` | N/A | Tone and depth of explanation |
| `editorial_preferences` | Score modifiers via category + tag matching | N/A |
| `briefing_philosophy.alert/default` | Rule-based state flag → tiebreaker boost | Lead insight framing |
| `briefing_philosophy.tone` | N/A | Shapes copy voice |
| `briefing_philosophy.depth` | Annotation count cap (needs enum normalization) | Conciseness constraint |
| `current_focus.*` | Structured features after schema prerequisites | Awareness of tracked state |
| `conversation_extracts` | N/A | Full background context (already delivered) |

---

## Implementation Sequence (revised after Codex review)

The original sequence (A: pinned metrics + state detection, B: generators, C: current_focus, D: arbiter) was reordered based on Codex's finding that the first dependency is richer candidate inventory and structured metadata, not state detection.

**Phase 1 — Schema and data prerequisites**
- Add `tags: list[str]` to `InsightCandidate` model
- Create `core/overview_editorial/vocabulary.py` with canonical tag constants
- Normalize `briefing_philosophy.depth` to enum (`summary` / `high_level` / `detailed`)
- Define Pydantic submodels for `current_focus` entries (`WatchEntry`, `RecentAction`, `UpcomingEvent`)
- Add write-side validation in `update_editorial_memory()` — normalize `current_focus` through submodels on write
- Update auto-seeder to write new `watching` shape and import vocabulary constants
- Update LLM auto-seeder prompt to constrain `current_focus` output shape
- Centralize concern-to-metric mapping in a single resolver with tests
- No user-visible change. Lays the foundation for everything else.

**Phase 2 — Generator enrichment + anchored metrics**
- Generators tag candidates at emission time using canonical vocabulary constants (e.g., `TAGS.PERFORMANCE_VS_BENCHMARK`, `TAGS.DAILY_PNL_SWINGS` — matching the exact strings in the editorial memory preference lists)
- Auto-seeder updated to use vocabulary constants for any preferences it writes (currently writes raw strings like `"performance_vs_benchmark"` — should import from `vocabulary.py`)
- Performance generator reads `primary_goals` → emits "system working" lead_insight candidate
- Generators read `concerns` → adjust attention thresholds
- Generators read `time_horizon` + `risk_tolerance` → scale thresholds
- `_compute_memory_fit()` matches on `{category} | tags` against preference lists
- `select_slots()` anchors up to 2 metrics from concerns resolver
- This is where the overview starts feeling personalized.

**Phase 3 — Policy refinement + state detection**
- `_detect_state()` based on structured breach signals (violations > 0, urgency == "alert")
- State flag included in `EditorialMetadata`
- State-aware tiebreaker boost in `rank()`
- Depth-based annotation cap using normalized enum

**Phase 4 — `current_focus` features**
- Requires structured schema + write-side validation from Phase 1
- `WatchlistInsightGenerator` for watched tickers (portfolio-only initially)
- User-defined event attention items from `upcoming`
- `recent_actions` passed to LLM arbiter as context (no deterministic exit-ramp suppression — descoped, see Section 4)

**Phase 5 — LLM arbiter refinement**
- Arbiter prompt includes `briefing_philosophy`, `conversation_extracts`, state flag (already has them — the change is what the arbiter is allowed to write)
- Expand arbiter output surface: consider adding `one_thing_that_matters` field to `EditorialMetadata` or `LeadInsight`
- Keep arbiter async — the core overview should not depend on a network model call (Codex recommendation)
- If new output fields are needed, add them to the Pydantic schema first as deterministic candidates, then let the arbiter refine them

---

## Open Questions (R3)

1. **Anchored metrics vs separate strip:** Should anchored metrics consume slots in the existing 6-slot strip, or should they be a separate "anchor strip"? (Decision: cap at 1-2 anchors within the existing strip per R1 recommendation. Revisit if users want more than 2 permanent metrics.)

2. **Concentration metric candidate gap:** The concentration generator only emits `diversification` (HHI). Should we add a `concentration` metric (top holding %) as a new candidate for anchoring? (Recommendation: yes, as part of Phase 2 generator enrichment. For now, `diversification` is the anchor for `concentration_risk`.)

3. **Tag vocabulary growth:** As generators are added, the vocabulary will grow. Should tags be a closed enum or an open set? (Decision: shared constants in `vocabulary.py`, open for extension. Generators import constants; policy matches against them. New generators add new constants. No runtime validation that tags are in the vocabulary — tests catch drift.)

---

## Codex Review Log

**R1 (2026-04-13):** 3 high, 3 medium findings.

| Finding | Severity | Resolution in R2 |
|---|---|---|
| Phase C not implementable — no structured schema for `current_focus` | High | Added data prerequisites as Phase 1. Structured schema required before features. |
| Phase D drifts past thin arbiter boundary | High | Pulled back. Arbiter stays async, stays limited. New output surfaces go to deterministic schema first. |
| Concerns mapping wrong — `lead_weight` may not exist, `factor_exposure → beta` is weak | High | Revised mapping. Centralized resolver. |
| Cross-cutting preferences need candidate tags, not generator branching | Medium | Added `tags: list[str]` to `InsightCandidate`. |
| Implementation order wrong — state detection before candidate enrichment | Medium | Reordered: schema → generators → state detection → focus → arbiter. |
| Phase D "current state" claim stale — arbiter already has full memory | Medium | Fixed. The limitation is what the arbiter can write, not what it sees. |
| Missing profile fields: `time_horizon`, `risk_tolerance`, `sophistication` | — | Added to Section 1 with concrete behavior per value. |
| `depth` needs normalization from prose to enum | — | Added normalization proposal. |

**R2 (2026-04-13):** 1 high, 3 medium, 1 low findings.

| Finding | Severity | Resolution in R3 |
|---|---|---|
| Tag/preference vocabulary mismatch — mixed user-facing strings, categories, and internal tags with no normalization | High | Unified vocabulary: generators tag with the same strings as preference lists. Shared constants in `vocabulary.py`. `_compute_memory_fit()` matches `{category} | tags` against preferences. Full vocabulary table added. |
| `current_focus` migration under-scoped — auto-seeder writes `{ticker, weight_pct}`, different from proposed shape | Medium | Added explicit migration/back-compat plan: duck-typing readers handle both shapes, auto-seeder updated to new shape, existing DB rows continue to work. |
| `recent_actions` exit ramp suppression not implementable — `ExitRamp.payload` is opaque string | Medium | Descoped from this design. Requires `ExitRamp` schema change to do properly — design separately if needed. `recent_actions` still useful as LLM arbiter context. |
| `depth` annotation cap has no enforcement — annotations are deduped but never ranked or truncated | Medium | Added type-priority truncation (`ask_about` > `editorial_note` > `context`), applied after dedup in `compose_brief()`. Scoring-based truncation deferred until annotation pool grows past ~8. |
| Concentration anchor overstated — generator only emits `diversification`, not `concentration` (top holding %) | Low | Fixed mapping to `diversification` only. Added open question about adding a `concentration` metric candidate in Phase 2. |

**R3 (2026-04-13):** 1 high, 2 medium, 1 low findings.

| Finding | Severity | Resolution in R4 |
|---|---|---|
| Vocabulary still inconsistent — Phase 2 examples used old-style tags (`benchmark_relative`, `daily_change`), auto-seeder writes raw strings | High | Phase 2 description updated to reference vocabulary constants. Auto-seeder update added to Phase 1 prerequisites. All writers use canonical vocabulary. |
| `current_focus` write-side still schema-loose — deferred validation means Phase 4 readers get unreliable data | Medium | Added Pydantic submodels (`WatchEntry`, `RecentAction`, `UpcomingEvent`). Write-side validation in `update_editorial_memory()`. Auto-seeder and LLM prompt constrained to target shapes. |
| Annotation depth cap has no within-type tie-break — generator ordering determines which annotations survive | Medium | Added within-type tie-break: sort by generator source order aligned with `lead_with` priorities (concentration > risk > performance). Stable, deterministic, doesn't depend on execution order. |
| Phase 4 still lists exit-ramp suppression, which was descoped in Section 4 | Low | Removed. Phase 4 now lists `recent_actions` as LLM arbiter context only. |

**R4 (2026-04-13):** 2 medium findings.

| Finding | Severity | Resolution in R4 |
|---|---|---|
| Annotation tie-break not implementable — `MarginAnnotation` has no source metadata, stated priority inconsistent with seed's `lead_with` order | Medium | Replaced generator-source ordering with `anchor_id` alphabetical tie-break. `anchor_id` is already on every annotation, provides stable content-based ordering. Noted optional `source_category` field as future enhancement if personalized priority is needed. |
| `current_focus` date fields are plain `str` — malformed strings pass write-side validation | Medium | Changed `added`/`date` fields from `str` to `datetime.date` in Pydantic submodels. Malformed dates rejected at write time. Phase 4 readers get validated dates. |

**R4 (2026-04-13):** 2 medium findings.

| Finding | Severity | Resolution in R4 |
|---|---|---|
| `current_focus` validation only covers `update_editorial_memory()` — LLM auto-seeder bypasses it, seeded users get unvalidated data | Medium | Added shared `normalize_current_focus()` function called by ALL write paths (MCP tool, deterministic seeder, LLM seeder). No write path persists without normalization. |
| `depth` normalization only covers MCP write path — seed file and existing DB rows still store prose, users without DB row get raw seed | Medium | Added shared `normalize_depth()` with keyword mapping. Called by all write paths + read-time fallback in `compose_brief()`. Seed file updated to enum value. System works even with legacy prose data. |

**R4b (2026-04-13):** 2 medium findings (contract details).

| Finding | Severity | Resolution in R4b |
|---|---|---|
| `normalize_current_focus()` output not JSON-serializable — `datetime.date` objects can't be `json.dumps()`'d for JSONB persistence | Medium | Normalizer returns plain dicts with ISO string dates (`date.isoformat()`). Submodels are validation-only; output is JSON-safe. |
| `normalize_depth()` keyword mapping ambiguous for legacy prose — "No full decomposition" matches both "high-level" and "detailed" | Medium | Added negation-safe matching with explicit precedence. "No " before "decomposition" cancels the "detailed" match. Current seed prose correctly maps to `"high_level"`. Inline code example with walkthrough. |

**R4c (2026-04-13):** 1 medium finding.

| Finding | Severity | Resolution in R4c |
|---|---|---|
| `normalize_depth()` negation check uses global `"no " not in text` — misclassifies "Detailed walkthrough, no summary" as not detailed | Medium | Simplified: dropped prose parsing entirely. `normalize_depth()` is now a simple enum check with safe default. All write paths produce enum values. Legacy prose falls back to `"high_level"`. |
