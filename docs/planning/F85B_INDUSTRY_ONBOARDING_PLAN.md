# F85b — `industry-onboarding` skill (REDUX)

**Status**: R6 — R5 PASSED with 2 P2 nits ("gates 2+3" wording bug + Tier 1 validation rule under-specified). Both addressed; ready for impl handoff.
**Date**: 2026-05-09
**Owner**: Henry
**Repo scope**: AI-excel-addin (skill + configs) + risk_module (reference + planning)
**Supersedes**: original F85b "transcribe editorial template" framing

---

## 1. Purpose

Ship an agent-driven `industry-onboarding` skill that takes an industry name (and an optional pre-curated peer set) and emits the canonical-comps configuration files needed to onboard a new operating-comps industry, **without requiring a hand-authored editorial template**.

This unblocks F85 ("v1.1 reference industries — Grocers + 3rd") for any industry whose peer set has EDGAR filings — the agent does the editorial work (peer set + KPI selection) by reading peer 10-Ks via the recently shipped EDGAR `operational_kpis` extraction.

The skill is the design-time KPI-selection counterpart to `peer-curation`. It does **not** change runtime KPI extraction (still regex-based via `transcript_kpi.pattern_hints`) and does **not** introduce a new schema kind. F86.b's runtime LLM-based KPI extraction stays out of scope.

**Inputs**: `industry_name` (free-form, e.g. `"Quick-service restaurants"`); optional `peer_tickers` (comma-separated); optional `industry_key` (snake_case, defaults to slugified `industry_name`).

**Outputs (proposed for user commit)**:
1. `AI-excel-addin/config/industry_kpis/<key>.yaml` (KPI registry)
2. `AI-excel-addin/config/comps_templates/operating_comps_<key>_v1.yaml` (manifest)
3. `AI-excel-addin/config/comps_templates/operating_comps_<key>_v1.fixture.csv` (metadata fixture)
4. *(conditional)* `AI-excel-addin/config/industry_taxonomy.yaml` patch (only when `industry_key` is not already present in `reference_industries`)

Skill does **not** git-commit. User reviews and commits.

---

## 2. Audit findings

### 2.1 Existing config layout (AI-excel-addin)

- `config/industry_kpis/hr_payroll.yaml` — only existing operating-comps KPI registry. Schema: `industry_key`, `display_name`, `template_manifest_id`, `kpis[]` (each with `key`, `label`, `units`, `definition`, `aliases[]`, `extraction.{kind,pattern_hints|formula|concept_name}`), `financial_metrics[]`.
- `config/comps_templates/operating_comps_hr_payroll_v1.yaml` — manifest for the HR/Payroll producer. Schema: `template_id`, `template_kind`, `industry_key`, `years_back`, `sections[].metrics[]` with `source.{kind, fmp_endpoint+fmp_field | edgar_concept | kpi_key | derived_formula}`.
- `config/comps_templates/operating_comps_hr_payroll_v1.fixture.csv` — flattened metadata view of the manifest, one row per (section × metric). Header: `section_order,section_name,metric_order,metric_key,label,units,aggregation,null_policy,source_kind,fmp_endpoint,fmp_field,edgar_concept,kpi_key,derived_formula`. Used as a parity fixture in `tests/schema/test_comps_template_operating_comps.py`.
- `config/industry_taxonomy.yaml` — drives `resolve_industry_key`. Maps each `industry_key` → `display_name` + `fmp_industries[]` + optional `fmp_industry_filter` regex. Already seeds `grocers` and `semiconductors` keys without matching KPI/manifest files (i.e. taxonomy is partially pre-populated; configs are the gating artifact).

### 2.2 Schema constraints (AI-excel-addin/schema/)

- `schema/kpi_registry.py` — `KPIRegistry`, `KPI`, `KPIExtraction`. `KPIExtraction.kind` is `Literal["transcript_kpi", "edgar_concept", "derived"]`. `transcript_kpi` requires `pattern_hints[]`; `edgar_concept` requires `concept_name`; `derived` requires `formula`. Mutual exclusion enforced. `KPIRegistry` rejects duplicate kpi keys.
- `schema/comps_template.py` — `CompsTemplateManifest`, `CompsManifestSection`, `CompsManifestMetric`, `CompsManifestSourceBinding`. `source.kind` is `Literal["fmp_endpoint","edgar_concept","transcript_kpi","derived","kpi"]` (manifest-side `kpi` is the indirection to `KPI` in the registry). Manifest validates: unique section names, unique section orders, unique metric keys per section, unique metric orders per section, `industry_key` required when `template_kind="operating_comps"`, exactly one of `years` or `years_back`.
- **Implication**: F85b emits only the 3 existing `KPIExtraction.kind` values. No schema bump.

### 2.3 Industry resolver

- `schema/industry_resolver.py` — `resolve_industry_key(fmp_profile)`: matches `_normalize_industry(profile["industry"])` against `industry_taxonomy.yaml.reference_industries.<key>.fmp_industries[]`, then optionally filters by regex against `companyName + description + sector + industry`. LRU-cached.
- Adding a new industry to taxonomy is a YAML edit; no code change.

### 2.4 Cross-repo loader (risk_module)

- `risk_module/utils/kpi_registry_loader.py` — `load_kpi_registry(industry_key)` reads `<AI-excel-addin>/config/industry_kpis/<key>.yaml` cross-repo, validates via `KPIRegistry.model_validate`. Returns `None` when no file exists.
- `risk_module/mcp_tools/industry.py:233-241` — wires `resolve_industry_key` + `load_kpi_registry`. Producer fires on `industry_key != "unknown"` and registry exists; emits `"operating_comps registry missing for industry_key=..."` warning otherwise.
- **Implication**: confirms TODO row claim — `industry_resolver + producer wire-up already key-extensible`. Zero risk_module code change required.

### 2.5 Manifest source dispatcher (recent, `c7558f45`)

- `risk_module/fmp/tools/manifest_source_dispatcher.py` — runtime resolver for `CompsManifestSourceBinding.kind`. Handles `fmp_endpoint`, `edgar_concept`, `transcript_kpi`, `derived`, `kpi` (with `kpi_key` indirection into `KPIRegistry`). Calls into `transcript_kpi_fetcher.py` (regex over FMP earnings transcripts) for `transcript_kpi` kinds. **Confirms**: runtime KPI extraction model is unchanged by F85b.

### 2.6 Existing skill pattern (peer-curation)

- `AI-excel-addin/api/memory/workspace/notes/skills/peer-curation.md` — frontmatter (`name`, `description`, `version`, `scope`, `agent_callable`, `resumable`, `agent_description`, `max_turns`, `max_budget_usd`, `persist_state`); methodology citation requirement; phased workflow with explicit gates; chunked `memory_write` deliverable (4 sequential calls); F84.D5 autonomous-mode block (recognized via `args="MODE=autonomous CALLER=... TICKER=..."` prefix, skips user-confirmation gate, appends decisions_log entry with verbatim rationale template).
- Reusable patterns: frontmatter shape, autonomous-mode block, gates + iron law, decision-log discipline, chunked persistence.

### 2.7 EDGAR `operational_kpis` schema (recent improvements)

Recap from session brief; full details in `Edgar_updater/edgar_api/documents/schemas.py:644-816` and `kpi_schema.py`:

- `operational_kpis` schema v1.1, 7 classes: `user_metric`, `volume_metric`, `retention_metric`, `pipeline_metric`, `footprint_metric`, `comp_metric`, `pricing_metric`.
- Per-extraction emits exact source span + structured `attributes{metric, value, direction, geography, ...}` + normalized fields `metric_name`, `metric_name_normalized`, `metric_kind` (absolute/growth/ratio/index), `factors[]` (volume/price/unit_economics/cost_structure/reinvestment/capital_sources), `segment_hint`, `value_raw`.
- Last-week improvements: filing-vocabulary constraint (no made-up labels), source-basis preservation (prose/table/merged), narrative-delta classification (Direction + magnitude), table-class typing (operating_kpi_table, segment_financial, etc.), prose+table merge dedup.

### 2.8 EDGAR MCP tool surface

- `get_filing_extractions(ticker, year, quarter, schema, source="auto", allow_stale=False)` → cached langextract spans for one filing/schema; cache-or-extract on miss. **Primary call for F85b discovery.**
- `get_operational_kpi_drivers(ticker, year, quarter, topic, source="auto", sections, max_chars)` → topic-driven filing-local KPI driver discovery; returns citation-ready rows. **Not used in v1** (overkill for cross-peer KPI-name aggregation; revisit for v2 quality validation).
- `search_extractions(ticker, schema, period_from, period_to, ...)` → read-only across cache; never extracts on miss. **Not used in v1** (single-ticker, F85b is multi-ticker fan-out).
- `list_extraction_schemas()` → schema registry discovery (8 schemas total). Not called at runtime by skill; documented for completeness.
- **Cost reality**: first call per (filing, `operational_kpis`) costs Gemini/OpenAI extraction (~30–120s typical, 300s timeout, 3-way fan-out). Subsequent reads cached. No `warm_extractions` tool. For 5 peers cold-start: ~5 sequential extractions, ~$1–3 LLM cost depending on filing size.

### 2.9 SKILL_CONTRACT_MAP convention

Per F83 follow-on commit `3206157`, each new skill needs a row in `SKILL_CONTRACT_MAP` (location: `AI-excel-addin/api/...` — TBD during impl). Row fields: skill name, scope, agent-callable bool, max_turns, max_budget_usd, output contract (file paths + patch ops if any).

---

## 3. Decisions

### D1 — Skill location: AI-excel-addin

**Decision**: Skill markdown lives at `AI-excel-addin/api/memory/workspace/notes/skills/industry-onboarding.md`, sibling to `peer-curation.md`, `comps-narrative.md`, `post-comps-landscape-refresh.md`.

**Rationale**: Configs being emitted live in AI-excel-addin. Skill harness, methodology units, SKILL_CONTRACT_MAP all live there. Peer-curation precedent.

### D2 — KPI corpus: EDGAR `operational_kpis`, transcripts deferred

**Decision**: v1 reads peer 10-Ks via `get_filing_extractions(schema="operational_kpis")` only. FMP earnings transcripts are out of scope for v1 KPI discovery (still relevant at runtime via `transcript_kpi_fetcher.py`, unchanged).

**Rationale**: 10-K MD&A is the densest single-document KPI surface; filing-vocabulary constraint produces source-faithful labels suitable for canonical-name selection; `operational_kpis` schema is purpose-built. Transcripts add cost + latency without v1 marginal value.

**v2 hook**: future revision can union transcripts for KPIs that surface in calls but not 10-K MD&A.

### D3 — Peer-curation coupling: one-shot internal sub-step

**Decision**: When `peer_tickers` is not provided, `industry-onboarding` invokes `peer-curation` in autonomous mode (`MODE=autonomous CALLER=industry-onboarding TICKER=<focal>`). When `peer_tickers` IS provided, skip the internal call and use the supplied list. Either way, peer set is fully realized before KPI discovery starts.

**Rationale**: One-shot UX cleanly maps to "industry name → configs"; autonomous-mode pattern already proven in F84.D5. Two-step flow preserved as the `peer_tickers` override path for users who want to curate first.

**Edge case**: peer-curation requires a Thesis to read. F85b is industry-level, not ticker-level — no Thesis exists for the industry itself. **Resolution**: skill uses `peer_tickers` arg as the canonical peer-set source; if absent, skill requires a `focal_ticker` arg whose Thesis can host peer-curation. Document this prerequisite explicitly.

### D4 — KPI selection: frequency-weighted union with class buckets

**Decision**: For each peer, fetch `operational_kpis` extractions for the most recent annual filing (10-K). Aggregate `metric_name_normalized` across peers; group by `class_hint` (user_metric, volume_metric, retention_metric, pipeline_metric, footprint_metric, comp_metric, pricing_metric). Select KPIs that appear in ≥`floor` peers (default `floor = max(2, ceil(N_peers/2))`). Propose top-K per class (default K=3) ordered by frequency, ties broken by extraction confidence (`grounded=True` count).

**Rationale**: Frequency thresholding filters one-off mentions; class bucketing maps cleanly to the schema's KPI taxonomy and gives users a structured review surface.

**Tunable**: floor + per-class K + max-total-K are skill-level constants exposed as args for power users. Defaults are conservative.

### D5 — `pattern_hints` regex derivation (always emit valid; runtime-parse-safe)

**Decision**: For each selected KPI, emit **at least 1 valid `pattern_hints` regex** that passes a 3-stage validation gate:

1. **Compile** — `re.compile(pattern)` succeeds.
2. **Match** — pattern matches the exemplar test string `metric_name + ": " + exemplar_value_raw`, capturing a named `value` group.
3. **Runtime-parse** — the captured value string passes `transcript_kpi_fetcher._parse_numeric(captured) is not None`. This is the load-bearing constraint: at runtime, the regex captures `(?P<value>...)`; `_match_value` returns that named group verbatim; `_parse_numeric` then strips commas + optional trailing `%`, casts to float. So the captured string must be a `_parse_numeric`-friendly numeric token (digits + commas + optional `.fraction` + optional `-` + optional trailing `%`).

**Capture discipline** — qualifiers, currency, sign-via-parens, and scale words live OUTSIDE the `(?P<value>...)` group. Only the numeric core is captured. (Parenthetical-negative shorthand `(71)%` is captured as `"71"` — sign is lost in v1 regex pipeline; F86.b runtime LLM upgrade handles paren-negative correctly. Document this as a v1 limitation in the methodology unit.)

**Validation flags** — regex gates 1 + 2 (compile + search) use the SAME flags as runtime: `re.IGNORECASE | re.MULTILINE` (per `fmp/tools/transcript_kpi_fetcher.py:96`). Gate 3 (`_parse_numeric`) is flag-independent. Without IGNORECASE, a fallback built from lowercased `metric_name_normalized` validates against `"membership renewal rate: (71)%"` but FAILS validation against the source-faithful capitalized `"Membership Renewal Rate: (71)%"` even though runtime would match it. Validation MUST mirror runtime to keep the "matches by construction" guarantee.

**Two-tier derivation** — both tiers must pass the same 3-stage gate (compile + match + `_parse_numeric`); only origin label and survivor count differ:
1. **Tier 1 (LLM-authored)**: Constrained LLM call (temperature 0) given the KPI's `metric_name_normalized` + `aliases[]` + `exemplar_value_raw` + existing `transcript_kpi_fetcher.py` conventions + the capture-discipline constraint above. Target: 2 patterns per KPI. Each candidate must pass the §6 S6 3-stage gate; survivors carry `regex_source="llm"`.
2. **Tier 2 (deterministic fallback, succeeds for any digit-bearing exemplar)**: build from the metric keywords + a units-aware value group whose capture is `_parse_numeric`-safe by construction (full template in §6 S6).

**User-review surface (skill output, NOT YAML)**: Per KPI, surface:
- `pattern_hints[]` proposed (from Tier 1 or Tier 2)
- `regex_source`: `"llm"` or `"fallback_default"` — flags KPIs that landed on Tier 2 as review-recommended
- 2 test strings (one positive constructed from exemplar, one negative)
- Compile status + match status (always green, by construction)

**Schema invariant**: `pattern_hints[]` is **never empty** in emitted YAML. KPIs whose exemplar lacks any `_parse_numeric`-friendly digit token are dropped from emission and surfaced in skill output as `rejected_kpis[]` with reason `pattern_hints_unbuildable_no_parseable_numeric` (canonical reason name; matches §6 S6).

**v1 acceptance**: emitted regex always valid; `regex_source="fallback_default"` KPIs are flagged for user edit before commit. Future hardening (F86.b runtime upgrade) replaces regex with LLM extraction at runtime, eliminating this concern entirely.

### D6 — Fixture CSV: deterministic regeneration from manifest YAML

**Decision**: `<id>.fixture.csv` is mechanically regenerated from `<id>.yaml`. One row per (section × metric) in section-order × metric-order. Header matches existing fixture format verbatim. No live FMP/EDGAR data needed.

**Rationale**: Existing `industry_comps_generic_v1.fixture.csv` and `operating_comps_hr_payroll_v1.fixture.csv` are metadata-only fixtures used for parity tests, not data fixtures. Deterministic regen avoids extra live-pull cost and matches the existing test pattern.

### D7 — Schema validation gate

**Decision**: Skill must run `KPIRegistry.model_validate(...)` and `CompsTemplateManifest.model_validate(...)` on emitted payloads BEFORE surfacing for user review. Any validation error blocks output and surfaces the exact pydantic error to the user. Fixture CSV is regenerated post-validation.

### D8 — User-confirm gate at "proposed canonical KPI list"

**Decision**: Single confirmation gate after KPI proposal, before file emission. User sees:
- Proposed industry_key + display_name
- Proposed peer set (with rationale if peer-curation ran internally)
- Proposed KPI list grouped by class, with `metric_name_normalized`, `units`, `aliases`, `pattern_hints` (×2), example test strings
- Proposed manifest section/metric structure
- Proposed taxonomy entry (if needed)

Confirmation grammar: `CONFIRM ONBOARD <INDUSTRY_KEY>` (analogous to `CONFIRM REPLACE PCTY PEERS` from peer-curation).

Non-confirmation outcomes match peer-curation: no/stop/maybe → no write; user edits → revise + ask again; ambiguous affirmation → display proposal again.

### D9 — Autonomous mode per F84.D5

**Decision**: Recognize `args="MODE=autonomous CALLER=<name> INDUSTRY_KEY=<key> [PEER_TICKERS=<csv>] [FOCAL_TICKER=<ticker>]"` prefix. In autonomous mode:
- Skip user-confirm gate
- Require `INDUSTRY_KEY` + (`PEER_TICKERS` OR `FOCAL_TICKER`); stop with `INSUFFICIENT_ARGS` otherwise
- Append `decisions_log` entry with verbatim template:
  ```yaml
  decision_type: "industry_onboarding_autonomous"
  rationale: "Autonomous industry-onboarding by {caller}. industry_key={industry_key}. Peers: {peer_list}. KPIs proposed: {kpi_list}. Sources: {edgar_filings}. To override, invoke industry-onboarding directly: this entry is the audit trail for autonomous operation."
  ```
- decisions_log entry attaches to the focal Thesis if present; otherwise to a synthetic `industry-onboarding/{industry_key}` log file (TBD during impl — see open question Q1)

### D10 — No git-commit; user owns the commit

**Decision**: Skill emits proposed file contents to the user via the chunked deliverable (per peer-curation §S11 pattern). Files are written to `data/users/<user>/workspace/notes/skills/industry-onboarding/{YYYY-MM-DD}-{industry_key}/` as a staging area. Final commit to `AI-excel-addin/config/...` is user-initiated outside the skill.

**Rationale**: Configs are repo-level; an autonomous git commit from a skill is a wider blast radius than the skill should own. User reviews the staging directory and copies into the AI-excel-addin repo.

---

## 4. Autonomous Mode (called from orchestration only)

Mirrors peer-curation §"Autonomous Mode" verbatim where applicable. Differences:

- Recognition: `args` begins with `MODE=autonomous`
- Required tokens: `CALLER=<name>` + `INDUSTRY_KEY=<key>` + (`PEER_TICKERS=<csv>` OR `FOCAL_TICKER=<ticker>`)
- No user-confirm gate
- After file emission to staging, append decisions_log entry per D9

Autonomous mode is intended for batch industry onboarding (e.g. "onboard the 10 industries our prospects ask about most often"). v1 has no orchestration caller; the path is wired for future use.

---

## 5. Out of scope

- **Runtime LLM-based KPI extraction** (F86.b) — F85b is design-time only; runtime KPI extraction stays regex-based via `transcript_kpi.pattern_hints`.
- **Per-quarter KPI granularity** (F86.a) — F85b emits annual-only configs matching existing operating-comps shape.
- **`industry_analysis.peer_comparison` rows** — that's `comparative-analysis` skill's contract; F85b is industry-level config generation, not per-ticker analysis.
- **8-K extraction** — `operational_kpis` schema accepts 8-K, but v1 uses 10-K only for cross-peer consistency.
- **Foreign filers (20-F / 6-K)** — extraction supported in EDGAR layer but US-only filers in v1.
- **`competitive-position` / `industry-landscape` writes** — F85b does not write Thesis fields beyond the optional decisions_log entry.
- **Editorial financial-comps** — universal-metric financial comps already use Track A's `editorial_peer_set` mechanism (different code path).
- **Skill-driven git commit** — D10.
- **Editorial template ingestion** — superseded by D2 (agent generates editorial from peers, not transcribes a doc).
- **`industry_taxonomy.yaml` heuristic auto-merge** — when industry_key is new, skill proposes a taxonomy entry; user reviews and applies. No automated taxonomy merging.

---

## 6. Steps

Steps are sequenced for incremental delivery. Each step is independently committable and testable.

### S1 — Skill markdown scaffold

Create `AI-excel-addin/api/memory/workspace/notes/skills/industry-onboarding.md` with peer-curation-style frontmatter:

```yaml
---
name: industry-onboarding
description: Agent-driven generation of canonical-comps configs for a new operating-comps reference industry; reads peer 10-Ks via EDGAR operational_kpis extraction, proposes KPI registry + manifest + fixture for user review.
version: 1.0
scope: industry
agent_callable: true
resumable: true
agent_description: 'Generate config/industry_kpis/<key>.yaml + config/comps_templates/operating_comps_<key>_v1.yaml + fixture from a peer set; supports autonomous mode for batch industry onboarding.'
max_turns: 12
max_budget_usd: 5.0
persist_state: true
---
```

Sections: When to Use / When NOT to Use / Iron Law / Autonomous Mode / Workflow (Phase 1–4) / Output Format / Tool Notes. ~250 lines target, modeled on peer-curation.md.

### S2 — Methodology unit

Create `AI-excel-addin/api/memory/methodology/strategic-evaluation/industry-onboarding-composition.md` (~1500 words). Covers: KPI taxonomy mapping (7 EDGAR classes → 3 schema kinds), pattern_hints derivation discipline, frequency-floor rationale, class-bucket K selection, fixture parity rule. Cited verbatim in skill's decisions_log: `Applied: methodology/strategic-evaluation/industry-onboarding-composition.md`.

### S3 — Phase 1: Scope + peer-set realization

Skill workflow Phase 1:
- **Step 1**: Confirm mode (interactive vs autonomous) + parse args.
- **Step 2**: Read existing `industry_taxonomy.yaml`. If `industry_key` already present, record `taxonomy_action="none"`; else `taxonomy_action="propose"`.
- **Step 3**: Realize peer set:
  - If `PEER_TICKERS` provided → use directly; record `peer_source="explicit"`.
  - Else if `FOCAL_TICKER` provided:
    - Read `Thesis(<FOCAL_TICKER>)`. If no Thesis exists OR Thesis is missing required fields per peer-curation's Phase 1 Step 2 (`industry_analysis.editorial_peer_set` slot, `business_overview`, `decisions_log`), stop with `INSUFFICIENT_DATA` and instruct caller to either (a) load/create the Thesis first, or (b) re-invoke with `PEER_TICKERS=<csv>` to skip peer-curation.
    - Otherwise, invoke `peer-curation` with `args="MODE=autonomous CALLER=industry-onboarding TICKER=<FOCAL_TICKER>"`; consume its `set_editorial_peer_set` output as the peer set.
  - Else (neither `PEER_TICKERS` nor `FOCAL_TICKER`) → stop with `INSUFFICIENT_ARGS`.

⛔ Gate: peer set ≥3 tickers (frequency floor implies ≥2; ≥3 gives a meaningful denominator).

### S4 — Phase 2: EDGAR KPI discovery

**Tool signatures pinned** (verified against `Edgar_updater/mcp_server.py`):
- `get_filings(ticker, year, quarter, source="auto")` — returns filings filed for that fiscal period; check `form` field on returned rows.
- `get_filing_extractions(ticker, year, quarter, schema, source="auto", allow_stale=False)` — cache-or-extract langextract spans.
- *(Note: `get_event_filings` accepts `form_types`/`limit` but is for event filings (8-K-class) only — does **not** support 10-K. Do not use for annual-filing discovery.)*

For each peer ticker, resolve most recent 10-K via descending-year probe. Both `get_filings` and `get_filing_extractions` return dicts with named arrays — explicit unwrap discipline:

```python
# Filings discovery — payload["filings"] is the list (verified at edgar_parser/tools.py:794)
target_year = None
for fy_candidate in [current_year, current_year - 1, current_year - 2]:
    payload = get_filings(
        ticker=peer,
        year=fy_candidate,
        quarter=4,
        source="auto",
    )
    filings = payload.get("filings", [])
    ten_k = next((f for f in filings if f.get("form") == "10-K"), None)
    if ten_k is not None:
        target_year = fy_candidate
        break

if target_year is None:
    record peer as `unresolved_10k`
    continue  # do not block aggregate; surface in skill output

# Extraction — payload["extractions"] is the list (verified at edgar_api/routes/extractions.py:77,450)
ext_payload = get_filing_extractions(
    ticker=peer,
    year=target_year,
    quarter=4,
    schema="operational_kpis",
    source="auto",
    allow_stale=False,
)
extractions = ext_payload.get("extractions", [])
```

Persist raw extractions to staging dir: `staging/{industry_key}/extractions/{ticker}_{target_year}.json`.

**FY discovery quarter convention**: 10-K filings are indexed under `quarter=4` (full-year). Do NOT iterate quarters 1–3 for 10-K discovery — the descending-year probe alone is sufficient (verified for off-cycle fiscal years like AAPL/PCTY).

**Concurrency**: sequential v1 (extraction is the bottleneck; parallel fan-out exceeds the EDGAR-side 3-worker cap and risks Gemini throttling). Budget per peer: 120s typical, 300s hard timeout per filing.

⛔ Gate: ≥80% of peers return non-empty extraction sets (i.e. resolved 10-K + non-empty `KpiObservation` list). Below that threshold, surface error + stop. Peers that fail filing resolution are listed in skill output but do not block aggregation if the 80% floor holds.

### S5 — Phase 2 cont.: cross-peer aggregation

Aggregator implementation (Python; lives in skill harness, not as a separate module v1):

```
inputs: list of KpiObservation lists per peer (each obs has values[ValuePoint], class_hint, metric_name, metric_name_normalized, grounded)
output: list of KPI candidates with (metric_name_normalized, class_hint, frequency, peers, exemplar_value_raw, exemplar_metric_name, aliases[])
```

Steps:
1. Flatten `(peer, KpiObservation)` rows.
2. Group by `(metric_name_normalized, class_hint)`.
3. Compute frequency = distinct peers in group.
4. Filter: frequency ≥ `floor` (default `max(2, ceil(N_peers/2))`).
5. Per `class_hint`, sort by frequency desc, take top `K` (default 3).
6. For each survivor:
   - Collect `metric_name` variants across peers as `aliases[]` (de-duplicated, lowercased).
   - Select **exemplar_value_raw** from the underlying `ValuePoint` (per `KpiObservation.values[]` — `value_raw` lives on the value point, not at observation top-level — see `Edgar_updater/edgar_api/documents/kpi_schema.py:49,74`):
     ```python
     # Prefer grounded observation, then a value point with successful normalization:
     candidates = [obs for obs in group_obs if obs.get("grounded")] or list(group_obs)
     for obs in candidates:
         for vp in obs.get("values", []):
             if vp.get("value_normalized") is not None and vp.get("value_raw"):
                 exemplar_value_raw = vp["value_raw"]
                 exemplar_metric_name = obs["metric_name"]
                 break
         else:
             continue
         break
     else:
         # Fallback: first non-empty value_raw regardless of normalization; carry parent obs for metric_name.
         fallback = next(
             ((obs, vp) for obs in candidates for vp in obs.get("values", []) if vp.get("value_raw")),
             None,
         )
         if fallback is not None:
             exemplar_obs, exemplar_vp = fallback
             exemplar_value_raw = exemplar_vp["value_raw"]
             exemplar_metric_name = exemplar_obs["metric_name"]
         else:
             exemplar_value_raw = None
             exemplar_metric_name = None
     ```
   - If no `value_raw` found anywhere → drop KPI to `rejected_kpis[]` with reason `no_exemplar_value`.

### S6 — Phase 2 cont.: pattern_hints derivation (per D5 two-tier rule)

For each KPI candidate:

**Tier 1 (LLM)**:
- Prompt: existing `transcript_kpi_fetcher.py` regex conventions (named `(?P<value>...)`); seed examples from `hr_payroll.yaml`; KPI's `metric_name_normalized`, `aliases[]`, `exemplar_value_raw`, `units`.
- Temperature 0; deterministic output expected for a given (metric, exemplar) tuple.
- Validate each candidate: regex must `re.compile`, must contain a named `value` group, AND must match the exemplar test string `metric_name + ": " + exemplar_value_raw`.
- Survivors → `pattern_hints[]`, `regex_source="llm"`.

**Tier 2 (deterministic fallback, succeeds for any digit-bearing exemplar; runtime-parse-safe)**:

EDGAR `value_raw` preserves source-faithful text including qualifiers (`"approximately 55"`, `"over 70%"`), currency (`"$1.2 billion"`), parens-as-negative (`"(71)%"`), scale words (`"million"`/`"billion"`), and multi-segment values (`"92.9% in U.S., 90.5% worldwide"`).

The `(?P<value>...)` group must capture **only the numeric core** (digits + commas + optional `.fraction` + optional sign + optional trailing `%`) so `transcript_kpi_fetcher._parse_numeric` accepts it at runtime (`fmp/tools/transcript_kpi_fetcher.py:146-159`). Qualifiers, currency, scale words, and outer parens live in NON-CAPTURING groups around it.

```python
# Non-capturing context groups (consumed but not captured):
QUALIFIER  = r"(?:approximately|about|nearly|over|under|roughly|circa|~)?\s*"
CURRENCY   = r"\$?\s*"
OPEN_PAREN = r"\(?"              # optional open paren (for paren-negative shorthand)
CLOSE_PAREN= r"\)?"              # close paren (independently optional from OPEN_PAREN)
SCALE      = r"(?:\s*(?:thousand|million|billion|trillion))?"

# Pure numeric capture group (this is what _parse_numeric will see):
NUMERIC = r"-?\d[\d,]*(?:\.\d+)?"   # _parse_numeric accepts: digits, commas, optional fraction, optional sign

# Percent-suffix lives OUTSIDE capture so paren-suffix order `(71)%` works:
PERCENT_SUFFIX = r"(?:\s*(?:%|percent(?:age)?))"

# Units-aware patterns. Capture is ONLY the numeric core. Percent/scale/parens consumed outside.
# percent  → qualifier + open_paren + (capture pure digits) + close_paren + % suffix.
percent_pattern = rf"{QUALIFIER}{OPEN_PAREN}(?P<value>{NUMERIC}){CLOSE_PAREN}{PERCENT_SUFFIX}"
# Note: parens-as-negative `(71)%` captures `"71"`; _parse_numeric returns 71.0; sign is lost (documented v1 limitation).
# count    → qualifier + open_paren + (capture pure digits) + close_paren + scale.
count_pattern = rf"{QUALIFIER}{OPEN_PAREN}(?P<value>{NUMERIC}){CLOSE_PAREN}{SCALE}"
# usd      → qualifier + currency + open_paren + (capture pure digits) + close_paren + scale.
usd_pattern = rf"{QUALIFIER}{CURRENCY}{OPEN_PAREN}(?P<value>{NUMERIC}){CLOSE_PAREN}{SCALE}"

# Metric-name preamble — word-boundary on alias phrases first, individual keyword words as fallback.
# Filter stopwords (the/of/and/a) and short tokens (len<4) to reduce overmatch.
STOPWORDS = {"the", "of", "and", "a", "an", "in", "on", "for", "to", "is", "are", "was", "were"}
def _build_preamble(metric_name_normalized: str, aliases: list[str]) -> str:
    phrases = sorted(
        {p.strip().lower() for p in [metric_name_normalized, *aliases] if p.strip()},
        key=len, reverse=True,  # prefer longer phrases first
    )
    # Try alias phrases as multi-word units (with word boundaries):
    phrase_alts = [rf"\b{re.escape(p)}\b" for p in phrases if len(p) >= 4]
    # Fallback: individual keyword words from metric_name_normalized that survive filter:
    keywords = [
        re.escape(w) for w in metric_name_normalized.lower().split()
        if w not in STOPWORDS and len(w) >= 4
    ]
    word_alts = [rf"\b{w}\b" for w in keywords] if keywords else []
    alts = phrase_alts + word_alts
    return rf"(?:{'|'.join(alts)})[\s\S]{{0,40}}?" if alts else r""

preamble = _build_preamble(metric_name_normalized, aliases)
pattern_hints_0 = preamble + units_group_for(units)
```

**Validation gate** (3 stages, all mandatory; flags MUST mirror runtime `re.IGNORECASE | re.MULTILINE` per `transcript_kpi_fetcher.py:96`):
1. `re.compile(pattern, flags=re.IGNORECASE | re.MULTILINE)` succeeds.
2. `m = re.search(pattern, metric_name + ": " + exemplar_value_raw, flags=re.IGNORECASE | re.MULTILINE)` returns a match with named group `value`.
3. `transcript_kpi_fetcher._parse_numeric(m.group("value")) is not None` — the captured string is runtime-parse-safe.

By construction, any exemplar with at least one digit token of `_parse_numeric`-friendly shape satisfies all three gates. Edge cases:
- `"approximately 55"` (count) → QUALIFIER consumes `approximately `, OPEN/CLOSE_PAREN empty, capture `"55"`, `_parse_numeric` → 55.0 ✓
- `"approximately 5%"` (percent) → QUALIFIER consumes `approximately `, OPEN/CLOSE_PAREN empty, capture `"5"`, PERCENT_SUFFIX consumes `%`, `_parse_numeric` → 5.0 ✓
- `"$1.2 billion"` (usd) → QUALIFIER empty, CURRENCY consumes `$`, capture `"1.2"`, SCALE consumes ` billion`, `_parse_numeric` → 1.2 ✓ *(scale lost; documented v1 limitation — F86.b handles scale)*
- `"(71)%"` (percent) → QUALIFIER empty, OPEN_PAREN consumes `(`, capture `"71"`, CLOSE_PAREN consumes `)`, PERCENT_SUFFIX consumes `%`, `_parse_numeric` → 71.0 ✓ *(sign lost; documented v1 limitation)*
- `"over 70%"` (percent) → QUALIFIER consumes `over `, capture `"70"`, PERCENT_SUFFIX consumes `%`, `_parse_numeric` → 70.0 ✓
- `"92.9% in U.S., 90.5% worldwide"` (percent) → matches first percent occurrence, capture `"92.9"`, PERCENT_SUFFIX consumes `%`, `_parse_numeric` → 92.9 ✓

**KPI rejection (rare path)**: if Tier 2's gate-3 still fails (exemplar has no `_parse_numeric`-friendly digit token — e.g. purely directional text like `"increased"`, `"strong"`, or all-non-numeric like `"approximately"`), KPI is dropped from emission and added to skill output `rejected_kpis[]` with reason `pattern_hints_unbuildable_no_parseable_numeric`. Schema validation never sees an empty `pattern_hints[]`.

### S7 — Phase 3: Emission (exact field shape match required)

Build payloads. Field-for-field parity with `operating_comps_hr_payroll_v1.yaml` is required so the existing loader/test machinery accepts the new files unchanged.

**`industry_kpis/<key>.yaml`** (`KPIRegistry`):
- `industry_key`
- `display_name`
- `template_manifest_id`: must equal `"operating_comps_<key>_v1"`
- `kpis[]` from S5 + S6, each with: `key`, `label`, `units`, `definition`, `aliases[]`, `extraction.{kind, pattern_hints | concept_name | formula}`
- `financial_metrics[]`: see Q2 resolution — defaults to `hr_payroll`'s software-flavored set (`revenue, sales_growth, sm_expense, rd_expense, capex_ratio, ebitda_margin, fcf_margin, fcf_conversion`) with explicit "user-edit-required for non-software industries" annotation in skill output

**`comps_templates/operating_comps_<key>_v1.yaml`** (`CompsTemplateManifest`) — emit ALL fields below in this order, matching the `hr_payroll` v1 manifest verbatim:
- `template_id`: `"operating_comps_<key>_v1"`
- `template_kind`: `"operating_comps"`
- `industry_key`
- `source_gsheet_id: null` *(emitted as null literal; required by manifest convention even when unused)*
- `source_gsheet_version`: `"f85b_<industry_key>_<YYYY_MM_DD>"` *(skill stamp; per `hr_payroll` precedent of `"trackb_fixture_2026_05_07"`)*
- `years_back: 8` *(matches `hr_payroll`)*
- `sections[]` ordered as:
  1. Growth (order=1): `revenue` (fmp_endpoint=income_statement, fmp_field=revenue), `sales_growth` (fmp_endpoint=ratios, fmp_field=revenueGrowth)
  2. Customer Base / Volume (order=2): KPIs from S5 + S6 with `source.kind=kpi` + `kpi_key=<key>`
  3. Investment (order=3): `sm_expense`, `rd_expense`, `capex_ratio` (matches `hr_payroll`; user-edits OK)
  4. Margins (order=4): `ebitda_margin`, `fcf_margin`, `fcf_conversion` (matches `hr_payroll`; user-edits OK)

`section.metric.source.kind` is `"kpi"` for KPI-backed metrics with `kpi_key` indirection (NOT `"transcript_kpi"` — that's the registry-side extraction kind, distinct from manifest-side source kind).

**Validation**: Run `KPIRegistry.model_validate(...)` + `CompsTemplateManifest.model_validate(...)` on the built payloads. Halt + surface error on failure (any failure here is a skill bug, not user input).

**Taxonomy patch** (when `taxonomy_action="propose"`):
- Build YAML patch entry under `reference_industries.<industry_key>`: `display_name`, `fmp_industries[]` collected from `fmp_profile.industry` of peer set (lowercase, deduplicated), `fmp_industry_filter` left null in v1 (user adds if peer set spans broad sectors).

**Fixture CSV regen**: reuse `AI-excel-addin/config/comps_template_loader.py:34` `manifest_fixture_rows(manifest)` rather than reimplementing. Header order matches `manifest_fixture_rows` output keys: `section_order, section_name, metric_order, metric_key, label, units, aggregation, null_policy, source_kind, fmp_endpoint, fmp_field, edgar_concept, kpi_key, derived_formula`.

### S8 — Phase 3 cont.: User-confirm display

Display the 4 proposed artifacts:
1. KPI registry preview (table view + raw YAML)
2. Manifest preview (section table + raw YAML)
3. Fixture CSV preview (first 10 rows)
4. Taxonomy entry preview (if applicable)

Show:
- `pattern_hints` per KPI with positive/negative test strings
- Frequency stats per KPI (e.g. `4/5 peers`)
- Rejected candidates with reasons (`below floor`, `no class_hint match`, `pattern_hints failed validation`)

Confirmation: `CONFIRM ONBOARD <INDUSTRY_KEY>`.

⛔ Gate per peer-curation pattern: do not proceed to staging-file write without exact confirmation, unless autonomous mode.

### S9 — Phase 4: Staging writes

Write to `data/users/<user>/workspace/notes/skills/industry-onboarding/{YYYY-MM-DD}-{industry_key}/`:
- `industry_kpis_<key>.yaml`
- `operating_comps_<key>_v1.yaml`
- `operating_comps_<key>_v1.fixture.csv`
- `industry_taxonomy_patch.yaml` (if applicable)
- `README.md` with copy-target instructions:
  ```
  cp industry_kpis_<key>.yaml      <repo>/AI-excel-addin/config/industry_kpis/<key>.yaml
  cp operating_comps_<key>_v1.yaml <repo>/AI-excel-addin/config/comps_templates/
  cp operating_comps_<key>_v1.fixture.csv <repo>/AI-excel-addin/config/comps_templates/
  # then merge industry_taxonomy_patch.yaml into industry_taxonomy.yaml manually
  ```

### S10 — Phase 4 cont.: Decision log + persistence

Decisions log entry (interactive mode):
```yaml
date: <ISO>
skill: "industry-onboarding"
decision: "<ONBOARD_PROPOSED|NO_WRITE>: industry_key=<key>, kpis=<n>, peers=<n>"
rationale: "Applied: methodology/strategic-evaluation/industry-onboarding-composition.md. Peer set basis: <peer_source>. KPI selection: frequency floor=<f>, top-K per class=<k>. EDGAR sources: <filing list>. To override: edit emitted configs in staging dir."
```

Autonomous mode appends the D9 verbatim template instead. Decisions log attaches to focal Thesis if present; else to synthetic `industry-onboarding/{industry_key}/decisions_log.yaml` (Q1 in §7).

Chunked `memory_write` (4 calls per peer-curation §11):
- 11a: header + scope + peer set + taxonomy state
- 11b: KPI candidates table + frequency stats + rejected list
- 11c: emitted YAML payloads (raw)
- 11d: decisions_log entry

### S11 — SKILL_CONTRACT_MAP entry

Add row in `/Users/henrychien/Documents/Jupyter/AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` per F83 precedent. Record: name, scope=`industry`, agent_callable=true, max_turns=12, max_budget_usd=5.0, output_contract = `staging dir + 4 file types (industry_kpis YAML, manifest YAML, fixture CSV, optional taxonomy patch)`.

### S12 — Tests

- `tests/skills/test_industry_onboarding_aggregator.py` — unit tests on the cross-peer aggregator (S5): frequency thresholding, class bucketing, top-K selection, alias collection, exemplar selection.
- `tests/skills/test_industry_onboarding_pattern_hints.py` — unit tests on regex derivation (S6) given fixed exemplar inputs (mocks LLM with fixed response set); validates compile + match against exemplar test strings.
- `tests/skills/test_industry_onboarding_emission.py` — golden tests for emitted YAML payloads given fixed aggregator output; runs `KPIRegistry.model_validate` + `CompsTemplateManifest.model_validate` on golden output.
- `tests/skills/test_industry_onboarding_fixture_parity.py` — fixture CSV regen is deterministic from manifest YAML; round-trip golden test.
- `tests/skills/test_industry_onboarding_autonomous_contract.py` — autonomous-mode arg parsing (recognition rule, INSUFFICIENT_ARGS path, decisions_log template emission).

Mocks: EDGAR `get_filing_extractions` returns canned `KpiObservation` payloads from a fixture set seeded from real PCTY/PAYC/PAYX/ADP/WDAY captures (one-time live capture during S4 impl, then mocked).

### S13 — Live-verify smoke (Grocers)

Pre-staged: taxonomy entry already exists for `grocers`. Live test:
- Peer set: pick from real grocery-store filers (e.g. KR, ACI, COST is excluded — wholesale; SFM, WMK, IMKTA candidates).
- Run `industry-onboarding INDUSTRY_KEY=grocers PEER_TICKERS=KR,ACI,SFM,WMK`.
- Expected: KPI candidates surface comp_metric (comparable sales), footprint_metric (warehouses/stores opened/closed), pricing_metric (membership fees, average ticket), volume_metric (transactions/units sold). Confirms class-bucket coverage.
- Cost ceiling: ≤$5, ≤10min wall clock for 4-peer cold-cache run.
- Outcome artifact: `data/users/henry/workspace/notes/skills/industry-onboarding/2026-MM-DD-grocers/` plus a QA writeup at `data/users/henry/workspace/notes/skills/industry-onboarding/2026-MM-DD-grocers-LIVE-VERIFY.md`.

### S14 — Producer end-to-end smoke

After user copies emitted Grocers configs into AI-excel-addin/config/:

1. **Cache invalidation**: `industry_resolver._load_taxonomy` is LRU-cached (`AI-excel-addin/schema/industry_resolver.py:50`). Long-running processes that imported `resolve_industry_key` before the taxonomy edit will not see the new key until either (a) the process restarts or (b) `_load_taxonomy.cache_clear()` is called. README in staging dir + S14 procedure must instruct the user to restart the relevant service (gateway / MCP / Celery worker per memory: "long-running processes hold stale module state") OR run a one-shot `python -c "from schema.industry_resolver import _load_taxonomy; _load_taxonomy.cache_clear()"` in any persistent host.
2. **Producer run**: invoke risk_module producer for KR (or focal grocer): `mcp_tools/industry.py:get_industry_peer_comparison` should resolve `industry_key=grocers`, load the new KPI registry, and emit operating_comps for the new industry.
3. **Verify**: producer return contains `peer_comparison.sections` with the new KPI rows; no `"operating_comps registry missing"` warning.

Confirms F85 unblocked.

---

## 7. Tests (consolidated)

| Test file | Asserts |
|---|---|
| `tests/skills/test_industry_onboarding_aggregator.py` | frequency thresholding; class bucketing; top-K selection; alias collection; exemplar `value_raw` selection prefers `grounded=True` |
| `tests/skills/test_industry_onboarding_pattern_hints.py` | 3-stage gate (compile + match with `re.IGNORECASE \| re.MULTILINE` flags + `_parse_numeric(captured) is not None`); rejection path surfaces `pattern_hints_unbuildable_no_parseable_numeric` for non-numeric exemplars; surviving KPIs flagged `regex_source="fallback_default"` when LLM tier produced 0 survivors |
| `tests/skills/test_industry_onboarding_emission.py` | `KPIRegistry.model_validate` + `CompsTemplateManifest.model_validate` pass on golden output; rejects malformed (missing field, duplicate keys, schema-violating extraction kind) |
| `tests/skills/test_industry_onboarding_fixture_parity.py` | fixture CSV regen deterministic; row count = sum of metrics across sections; header matches existing fixture format |
| `tests/skills/test_industry_onboarding_autonomous_contract.py` | autonomous args parsing; `INSUFFICIENT_ARGS` when missing `INDUSTRY_KEY` or both `PEER_TICKERS`/`FOCAL_TICKER`; decisions_log template emission verbatim |
| `tests/skills/test_industry_onboarding_taxonomy_patch.py` | taxonomy_action="none" when key already present; taxonomy_action="propose" produces well-formed YAML patch entry |
| Live-verify (manual, S13) | Grocers run produces valid configs; producer end-to-end smoke (S14) passes flag-on |

---

## 8. Risks and open questions

### R1 — `pattern_hints` regex quality (medium risk, mitigated)

**Risk**: LLM-derived regex from a single exemplar may match too narrowly (too literal) or too broadly (false positives at runtime).

**Mitigation**: 2 patterns per KPI, both validated against exemplar (3-stage gate); user-review surface flags Tier-2-fallback patterns via `regex_source="fallback_default"` (review-recommended, not blocked). v2 path: F86.b runtime LLM extraction sidesteps regex entirely.

### R2 — EDGAR cache cold-start cost (medium risk, accepted)

**Risk**: 5-peer × 1-filing cold-start = ~5 sequential extractions × 30–120s each = ~3–10 minutes wall clock + ~$1–3 LLM cost.

**Mitigation**: cache subsequent calls; document live-run cost in skill output; budget set to $5 / 12 turns. Re-runs are cheap.

### R3 — Peer set size sensitivity (low risk, parameterized)

**Risk**: 3 peers gives weak frequency signal (floor=2 → 67% threshold); 8 peers expensive without quality gain.

**Mitigation**: floor + K + max-total-K exposed as skill args; defaults conservative (3+ peers required, floor=`max(2, ceil(N/2))`).

### R4 — Industry-key collision (low risk, gated)

**Risk**: Skill proposes `industry_key="quick_service_restaurants"` but a similar key (`qsr` or `restaurants`) already exists in taxonomy.

**Mitigation**: S3 reads taxonomy upfront; collision detection compares slugified names + display names against existing keys; surface conflict to user in confirm gate; suggest manual override.

### R5 — User-review burden (medium risk, accepted)

**Risk**: Per-KPI regex review × 6–12 KPIs = 12–24 patterns to vet. Tedious.

**Mitigation**: surface batch-review format (table, not per-KPI prompt); only flag failed-validation patterns as required-edit. Autonomous mode skips review (acceptable for batch onboarding where downstream telemetry catches bad regex).

### R6 — Frequency floor on small peer sets (low risk, accepted)

**Risk**: With N=3 peers, floor=2 means a KPI must appear in 2/3 peers (67%) — may exclude legitimate KPIs that one company emphasizes more than others.

**Mitigation**: documented in methodology unit; user can override `floor=1` via skill arg for exploratory runs.

### Q1 — Decisions log location for autonomous mode (open)

When autonomous mode runs without a focal Thesis, where does the decisions_log entry go? Options:
- (a) Synthetic `industry-onboarding/{industry_key}/decisions_log.yaml` (parallel to per-Thesis log)
- (b) Skip decisions_log entirely in autonomous-no-Thesis mode; rely on staging dir + skill output
- (c) Require `FOCAL_TICKER` in autonomous mode (so a Thesis always exists)

**Recommendation**: (a) — preserves audit-trail symmetry with peer-curation. Resolved during impl if a simpler path emerges.

### Q2 — `financial_metrics[]` default for new industries (RESOLVED, v1)

**Resolution**: v1 ships `hr_payroll`'s set verbatim as the default (`revenue, sales_growth, sm_expense, rd_expense, capex_ratio, ebitda_margin, fcf_margin, fcf_conversion`). For non-software industries (e.g. Grocers — would prefer `sga_expense`, `capex_intensity`, `gross_margin`), the skill's user-confirm display flags this section with explicit annotation: `"⚠ financial_metrics defaults are software-flavored — REVIEW BEFORE COMMIT for non-software industries."` Autonomous mode emits the defaults without modification (telemetry-driven hardening in v1.1 if needed).

**v1.1 path**: per-class-of-industry defaults (`software`/`retail`/`industrials`/`healthcare`) keyed off the industry's dominant FMP sector. Deferred until usage shows demand.

### Q3 — Multi-industry-key per peer-set (deferred)

If peer set spans two reasonable industry classifications (e.g. payroll vs HCM), should the skill propose two industry_keys with overlapping peers? v1: one industry_key per skill run; user invokes twice for two industries.

---

## 9. Verification checklist (pre-commit)

Before marking the plan as PASS-ready and handing to Codex for impl:

- [ ] Skill markdown frontmatter matches peer-curation conventions (frontmatter keys + values)
- [ ] Methodology unit cited verbatim in decisions_log rationale (`Applied: methodology/strategic-evaluation/industry-onboarding-composition.md`)
- [ ] Autonomous-mode recognition rule + INSUFFICIENT_ARGS path implemented per D9
- [ ] All emitted YAML passes `KPIRegistry.model_validate` + `CompsTemplateManifest.model_validate` BEFORE staging
- [ ] Fixture CSV regen is deterministic from manifest YAML (no live data)
- [ ] Staging dir layout matches D10
- [ ] Tests S12 all green
- [ ] Live-verify (Grocers, S13) produces working configs
- [ ] Producer end-to-end smoke (S14) passes after user-copy

---

## 10. Acceptance

- `industry-onboarding` skill present in AI-excel-addin skill catalog, agent-callable, autonomous-mode capable
- Live-verified via Grocers run: ≤$5, ≤10min, configs validate, producer end-to-end smoke green
- F85 unblocked: any industry with ≥3 EDGAR-filer peers can be onboarded by the agent in one skill call
- Zero risk_module code changes; AI-excel-addin gets skill markdown + methodology unit + tests + (optional) SKILL_CONTRACT_MAP row
- TODO.md F85b row updated to `SHIPPED + LIVE-VERIFIED <date>` with commit refs and live-verify cost

---

## 11. Changelog

- **R0** (2026-05-09) — initial draft. Decisions D1–D10 locked from session conversation; outline approved by user.
- **R1** (2026-05-09) — Codex R0 returned `FAIL 2`. Addressed: P1.1 regex/schema contradiction (D5 + S6 rewritten as two-tier always-emit-valid; YAML never carries empty `pattern_hints[]`); P1.2 EDGAR tool flow pinned (S4 — `get_filings(ticker, year, quarter, source)` descending-FY probe + form filter, then `get_filing_extractions`; ruled out `get_event_filings` for 10-K). Addressed P2: LRU cache invalidation in S14; exact emission shape including `source_gsheet_id: null` + `source_gsheet_version` + reuse of `manifest_fixture_rows` in S7; SKILL_CONTRACT_MAP path pinned to `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` in S11; peer-curation `INSUFFICIENT_DATA` fallback in S3; Q2 financial_metrics resolved to ship hr_payroll defaults with explicit "review-before-commit" annotation.
- **R2** (2026-05-09) — Codex R1 returned `FAIL 2`. Addressed: P1.1 Tier 2 fallback was digit-leading (failed for qualifier-prefixed exemplars `approximately 55`, `(71)%`, `over 70%`, `$1.2 billion`); §3 D5 + §6 S6 Tier 2 construction widened with units-aware QUALIFIER + CURRENCY + SIGN + SUFFIX + SCALE non-capturing groups + 40-char preamble gap. Edge cases enumerated. Rejection reason renamed to `pattern_hints_unbuildable_no_numeric` (only triggers for purely directional value_raw). P1.2 §6 S4 missing dict-unwrap on EDGAR tool returns; pseudocode now explicitly unwraps `payload.get("filings", [])` (verified `edgar_parser/tools.py:794`) and `ext_payload.get("extractions", [])` (verified `edgar_api/routes/extractions.py:77,450`). FY discovery quarter convention pinned to `quarter=4`. P2 (R1 leftover) noted: HR YAML lists `Customer Base` before `Growth` physically while emitted manifests will list Growth first; loader sorts by `section.order`, so this is cosmetic and not blocking.
- **R3** (2026-05-09) — Codex R2 returned `FAIL 3`. Addressed: P1.1 (`(71)%` → R2's `percent_group` matched `(71%)` not `(71)%` because SUFFIX was inside capture); §6 S6 Tier 2 redesigned so `(?P<value>...)` captures **only** the numeric core. Outer parens now in non-capturing OPEN_PAREN/CLOSE_PAREN groups. P1.2 (R2 captures broke runtime `_parse_numeric` at `transcript_kpi_fetcher.py:146-159`); D5 + S6 added 3-stage validation gate (compile + match + `_parse_numeric is not None`); qualifiers/currency/scale moved OUTSIDE the capture; capture is now `_parse_numeric`-safe by construction. Documented v1 limitations: paren-as-negative loses sign; `billion`/`million` scale loses scale (F86.b handles both). P1.3 (`exemplar_value_raw` lookup wrong); §6 S5 explicit selection from `obs.get("values", [])` per `KpiObservation.values[]` schema (`Edgar_updater/edgar_api/documents/kpi_schema.py:74`); prefers `value_normalized is not None`; falls back to first non-empty `value_raw`; drops to `rejected_kpis[]` if none found. P2 (R2 leftover): preamble switched from substring to word-boundary phrase-first with stopword + short-token filter (alias phrases ranked by length desc, individual keywords as fallback).
- **R4** (2026-05-09) — Codex R3 returned `FAIL 1`. Addressed: P1.1 R3's `percent_pattern` still had `%` inside the capture group (via `NUMERIC_PCT`), so `(71)%` matched as `(71%)` not `(71)%`. Fixed by introducing `PERCENT_SUFFIX = r"(?:\s*(?:%|percent(?:age)?))"` OUTSIDE the capture and AFTER `CLOSE_PAREN`. Now `(71)%` → OPEN_PAREN consumes `(`, capture `"71"`, CLOSE_PAREN consumes `)`, PERCENT_SUFFIX consumes `%`; `_parse_numeric("71")` → 71.0. Capture groups are now numeric-pure (no `%`). All 6 enumerated edge cases re-walked. P2 cleanups: §6 S5 fallback path now sets BOTH `exemplar_value_raw` AND `exemplar_metric_name` (was setting only `exemplar_value_raw`). D5 schema-invariant rejection reason aligned with §6 S6: both now use `pattern_hints_unbuildable_no_parseable_numeric`.
- **R5** (2026-05-09) — Codex R4 returned `FAIL 1`. Addressed: P1 design-time validation gate used bare `re.search` while runtime uses `re.IGNORECASE | re.MULTILINE` (`fmp/tools/transcript_kpi_fetcher.py:96`); broke "matches by construction" guarantee for capitalized exemplars (`"Membership Renewal Rate: (71)%"` failed gate-2 even though runtime would match). Both gate-1 (`re.compile`) and gate-2 (`re.search`) now use the same flags as runtime. P2 cleanups: D5 stale "captured as `71%`" → `"71"`; S6 comment "matched close paren" → "close paren (independently optional)"; S12 test-row updated to assert all 3 gates including `_parse_numeric(captured) is not None`; stale `_review_required` flag mentions replaced with `regex_source="fallback_default"` per current contract.
- **R6** (2026-05-09) — Codex R5 returned **`VERDICT: PASS`** with 2 P2 nits. Addressed: D5 wording corrected — "gates 1 + 2 (compile + search) use IGNORECASE/MULTILINE; gate 3 (`_parse_numeric`) is flag-independent" (was incorrectly grouped as "gates 2 + 3"). Tier 1 description updated to explicitly require survivors pass the same 3-stage gate as Tier 2; only origin label (`regex_source="llm"` vs `"fallback_default"`) differs. Plan is implementation-ready.
