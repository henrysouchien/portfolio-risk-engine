# Track B — Operating Comps + Per-Industry KPI Registry (Canonical Comps Framework)

**Status**: DRAFT R0 — implementation plan for Track B of the canonical comps framework.
**Created**: 2026-05-07.
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 (Codex PASS) — see §5 for Track B scope.
**Prerequisites**:
- Track 0 (`SCHEMA_AND_PATCH_OPS_PLAN.md` R4 PASS) — SHIPPED on AI-excel-addin commit `7ce654d`. Provides `OperatingComparison`, `TimeseriesGroup`, `TimeseriesMetric` schemas + `industry_resolver.resolve_industry_key()` + source registry.
- Track C (`EDITORIAL_PEER_SET_PLAN.md` R4 PASS) — SHIPPED on risk_module commit `24af19d5`. Provides `resolve_peer_universe()` helper.
- Track A (`INDUSTRY_COMPS_ARTIFACT_PLAN.md` R5 PASS) — SHIPPED on risk_module commit `ff3ff50f` + AI-excel-addin commit `85543e4`. Provides `manifest_source_dispatcher.py` (extensible by `kind`), `comps_aggregator.py`, dual-write + flag pattern.

**Authoritative code references** (verified by file read 2026-05-07):
- `AI-excel-addin/schema/thesis_shared_slice.py:455-472` — `TimeseriesMetric`, `TimeseriesGroup`, `OperatingComparison` types
- `AI-excel-addin/schema/thesis_shared_slice.py:510` — `IndustryAnalysis.operating_comparison: OperatingComparison | None = None`
- `risk_module/fmp/tools/manifest_source_dispatcher.py` — Track A's dispatcher with `kind: fmp_endpoint` + `kind: derived` handlers (Track B extends)
- `risk_module/utils/comps_aggregator.py` — Track A's median/mean aggregator (Track B reuses for `median_series`)
- `risk_module/mcp_tools/industry.py` — Track A's manifest-driven dual-write producer (Track B extends to also emit `operating_comparison`)
- `/Users/henrychien/Documents/Jupyter/edgar-parser/` — sibling repo with EDGAR parsing (concept extraction API verified at impl start)
- Editorial template of record (Google Drive, per session memory): `SIA-strategic-operating-comps-Grocers` and `SIA-strategic-operating-comps-SheetsFinance` — multi-year operating comps; HR-Payroll is the best-documented reference industry

---

## 1. Purpose

Ship the **operating comps producer** — a multi-year, per-industry, KPI-driven artifact populating `industry_analysis.operating_comparison`. Closes Track B of the canonical comps framework.

What's new vs Track A:
- **Multi-year time-series** (not single snapshot)
- **Per-industry KPI registry** (operational metrics like Clients, Retention, Revenue per Client — not in FMP standardized financials)
- **EDGAR + transcript extraction** as data sources alongside FMP
- **Per-industry manifest** (e.g., `operating_comps_hr_payroll_v1.yaml`) instead of generic
- **Skips when `industry_key=="unknown"`** (operational KPIs are industry-specific by definition; per Track 0 D9 and framework)

What's inherited unchanged from Track A:
- Manifest-driven assembly via extended `manifest_source_dispatcher`
- Cell-level citations + source registry
- Median/mean aggregation
- Track C peer resolution
- Feature-flag gating
- Lazy cross-repo imports

---

## 2. Audit findings (grounded by code read)

| Finding | File / location | Implication |
|---|---|---|
| `TimeseriesMetric` shape: `{key, label, units, series: dict[str, dict[int, CompMetricCell]], median_series: dict[int, CompMetricCell]}` | `thesis_shared_slice.py:455-461` | Track B builds this shape per metric: outer dict keyed by ticker, inner dict keyed by year, value is `CompMetricCell` (same shape as Track A — value + source_refs + derived) |
| `OperatingComparison.years: list[int]` is part of the artifact, not the manifest | `thesis_shared_slice.py:471` | Manifest specifies which years to fetch (e.g., `years_back: 8`); artifact stores resolved years (e.g., `[2018, 2019, ..., 2025]`) |
| `IndustryAnalysis.operating_comparison: OperatingComparison \| None = None` | `thesis_shared_slice.py:510` | Field is optional — Track B writes None when industry_key="unknown" (or omits the field entirely) |
| Track A's dispatcher takes `(binding, fmp_response_bundle, focal_ticker)` and returns `DispatchResult(value, source_record)` per `kind` | `manifest_source_dispatcher.py:58-100` | Track B extends with two new branches: `kind: edgar_concept` + `kind: transcript_kpi`. Same return shape. |
| Track A's producer at `mcp_tools/industry.py` returns flat top-level dict; flag-on adds `peers, sections, industry_key, ...` | `mcp_tools/industry.py` (Track A) | Track B further extends top-level: add `operating_comparison` field when flag on AND industry_key is known. Strictly additive. |
| `resolve_industry_key(fmp_profile)` (Track 0) returns reference industry or `"unknown"` | `AI-excel-addin/schema/industry_resolver.py` | Track B short-circuits when key is unknown — does not produce operating_comparison; keeps Track A's snapshot artifact untouched |
| EDGAR parser is a sibling repo; concept extraction API not yet verified | `/Users/henrychien/Documents/Jupyter/edgar-parser/` | Verified at impl start. Per session memory, EDGAR KPI extraction is "in progress"; Track B may need to provide a thin extraction wrapper if the parser doesn't expose a per-concept-per-year API |
| Editorial operating-comps templates exist (Grocers, HR-Payroll-shaped SheetsFinance) | (Google Drive) | Reference industry for v1: **HR-Payroll** — KPIs: Clients, % client growth, Retention, Revenue per client, S&M as % of sales, R&D as % of sales, CapEx as % of revenue, EBITDA margin, FCF margin (per editorial template) |

**Gap summary**: Track B has zero schema work (Track 0 shipped it), zero peer-resolver work (Track C shipped it), and the dispatcher pattern is established (Track A shipped it). What's new is the per-industry KPI definitions, the EDGAR/transcript dispatcher kinds, the time-series collection orchestration, and the per-industry manifest content.

---

## 3. Locked design decisions

### TB.D1. Reference industry for v1: HR-Payroll
First per-industry KPI registry + manifest target HR-Payroll (PCTY, PAYC, PYCR, CDAY, ADP, PAYX, WDAY) — best documented in editorial templates. KPIs include Clients, Retention, Rev/Client, S&M %, R&D %, CapEx %, EBITDA margin, FCF margin. v1 ships HR-Payroll only; Grocers + a third reference industry follow in v1.1.

### TB.D2. KPI registry yaml at `config/industry_kpis/<industry_key>.yaml` (per Track 0 D4)
Definitions only — no `peer_universe` (per Track 0 / framework D5). Schema:
```yaml
industry_key: hr_payroll
display_name: HR / Payroll
template_manifest_id: operating_comps_hr_payroll_v1
kpis:
  - key: clients
    label: Clients
    units: count
    definition: "Total customers paying for payroll/HCM service"
    aliases: [customers, subscribers, merchants]
    extraction:
      sources: [transcript, ir_release, mdna]
      pattern_hints: ["client count", "we serve N customers"]
  - key: retention
    label: Retention
    units: percent
    definition: "Annual revenue retention rate"
    extraction:
      sources: [transcript, ir_release]
      pattern_hints: ["retention rate", "% retention"]
  - key: revenue_per_client
    label: Revenue per client
    units: usd
    derived_from:
      formula: revenue / clients
financial_metrics:
  # Universal financial metrics, ordered per template manifest
  - revenue
  - sales_growth
  - sm_expense
  # ...
```

The KPI registry is a **content** layer (per-industry KPI definitions); the manifest is a **structure** layer (per-industry rendering shape). They're separate files.

### TB.D3. Per-industry operating-comps manifest at `config/comps_templates/operating_comps_<industry_key>_v1.yaml`
Mirrors Track 0's manifest shape but for time-series with `template_kind: "operating_comps"`. Sections, metrics, source bindings, ordering — same structure as `industry_comps_generic_v1.yaml`. Source bindings reference KPI keys from the registry via new `kind: kpi` (looks up KPI definition from registry, then dispatches per the KPI's `extraction.sources`).

Companion fixture CSV at `<manifest_id>.fixture.csv` per Track 0 §7.7.

### TB.D4. Dispatcher extends with `kind: edgar_concept`, `kind: transcript_kpi`, and `kind: kpi`
Track A's `manifest_source_dispatcher.py` adds three new branches:
- `kind: kpi` — looks up the KPI in the registry by `kpi_key`, then dispatches per the KPI's `extraction.sources` (transcript/edgar/etc.). Indirection layer that lets manifests reference KPIs by key without duplicating extraction config.
- `kind: edgar_concept` — fetches a us-gaap concept value for ticker × fiscal year via the EDGAR parser. Returns `(value, SourceRecord)` where `type="filing"`.
- `kind: transcript_kpi` — fetches a KPI value from earnings transcripts via pattern-matching against `pattern_hints` from the KPI registry. Returns `(value, SourceRecord)` where `type="transcript"`.

Both new kinds defer the per-year resolution to Track B's time-series orchestrator (next decision); the dispatcher just handles "give me this value for ticker X for year Y".

### TB.D5. Time-series orchestrator: new `risk_module/utils/timeseries_collector.py`
Pure orchestration module that:
1. Resolves the year range (manifest specifies `years_back: 8` or `years: [2018, ..., 2025]`)
2. For each peer × KPI × year, calls the dispatcher with the appropriate binding
3. Aggregates into `series: dict[ticker, dict[year, CompMetricCell]]`
4. Computes `median_series` per year via Track A's `comps_aggregator`

Pure function: takes inputs explicitly, returns the series dict + sources list. Testable without network calls via dispatcher mocking.

### TB.D6. `industry_key="unknown"` skips operating_comparison entirely
Per Track 0 D9 + framework: when `resolve_industry_key()` returns `"unknown"`, Track B does NOT produce `operating_comparison`. Producer's flag-on output omits the `operating_comparison` field (or sets it to None). Track A's snapshot artifact (`peer_comparison.sections`) is unaffected — that uses the generic manifest and works for any ticker.

For tickers WITH a known industry but no KPI registry yet (extension industries beyond HR-Payroll), Track B fails-loud at producer entry per project's "fail loudly" pattern. Caller then knows to fall back to snapshot-only.

### TB.D7. Single MCP tool produces both Track A and Track B output
`industry_peer_comparison()` (Track A) is extended to ALSO emit `operating_comparison` when flag on + industry_key known. No new MCP tool surface. Top-level dict gains one more field:

**Flag on, industry_key="hr_payroll"** (a PCTY/PAYC/etc.):
```python
{
    "peers": [...],                           # Track A legacy preserved
    "sections": [...],                        # Track A snapshot
    "industry_key": "hr_payroll",
    "template_manifest_id": "industry_comps_generic_v1",  # Track A manifest
    "as_of": "...",
    "sources": [...],                         # Combined sources from both A+B
    "operating_comparison": {                 # NEW (Track B) — present iff industry known
        "industry_key": "hr_payroll",
        "template_manifest_id": "operating_comps_hr_payroll_v1",
        "years": [2018, ..., 2025],
        "metric_groups": [...]
    }
}
```

**Flag on, industry_key="unknown"** (e.g., AAPL): same as today's Track A flag-on — no `operating_comparison` field.

**Flag off**: legacy `{"peers": [...]}` only (preserved through both Track A and Track B).

### TB.D8. EDGAR + transcript extraction wrappers — interface only, impl-start verified
Track B introduces two thin extraction wrappers:
- `risk_module/fmp/tools/edgar_concept_fetcher.py` — function `fetch_concept(ticker, concept_name, fiscal_year) -> (value, raw_payload, retrieved_at)`. Wraps existing edgar-parser API (verified at impl start).
- `risk_module/fmp/tools/transcript_kpi_fetcher.py` — function `fetch_kpi_from_transcripts(ticker, kpi_key, kpi_definition, fiscal_year) -> (value, raw_payload, retrieved_at)`. Uses FMP earnings transcripts + pattern matching from the KPI registry.

Both wrappers handle their own caching (parallel structure to Track A's `_peer_metric_snapshot_cache`). Cache TTL: 24 hours per peer × KPI × year (operating data changes much slower than market data).

The edgar-parser and FMP transcripts API surfaces are **verified at impl start** by reading `/Users/henrychien/Documents/Jupyter/edgar-parser/edgar_parser/` and existing FMP transcript code. If APIs don't expose what Track B needs, the wrapper's first impl phase establishes a thin adapter layer.

### TB.D9. Same flag, same dual-write semantics
`INDUSTRY_ANALYSIS_V1_2_ENABLED` (shared with Track A). When off, no Track B output (no operating_comparison). When on, Track B's `operating_comparison` ships alongside Track A's `sections`.

Lazy cross-repo imports per Track A TA.D9 — manifest loading from AI-excel-addin happens inside flag-on branch only.

### TB.D10. Reference industry registry + manifest commit alongside producer code
Track B's first impl phase commits:
- `AI-excel-addin/config/industry_kpis/hr_payroll.yaml` (KPI registry)
- `AI-excel-addin/config/comps_templates/operating_comps_hr_payroll_v1.yaml` (manifest)
- `AI-excel-addin/config/comps_templates/operating_comps_hr_payroll_v1.fixture.csv` (companion fixture)

Producer code (risk_module side) is decoupled from these — it loads via `load_comps_template_manifest()` and the new KPI-registry-loader helper. Adding more reference industries (Grocers, +1) in v1.1 requires zero risk_module changes.

---

## 4. File-by-file changes

### risk_module (primary)

**Modified**: `risk_module/fmp/tools/manifest_source_dispatcher.py`
- Add three new `kind` branches: `kpi`, `edgar_concept`, `transcript_kpi`
- For `kpi`: indirection layer (load from registry, dispatch per `extraction.sources`)
- For `edgar_concept` / `transcript_kpi`: call respective fetcher wrappers (TB.D8); construct SourceRecord with `type="filing"` or `type="transcript"` per Track 0 R4 enum mapping

**New**: `risk_module/fmp/tools/edgar_concept_fetcher.py` (per TB.D8)
- `fetch_concept(ticker, concept_name, fiscal_year) -> (value, raw_payload, retrieved_at)`
- Internal cache (24h TTL, key: `(ticker, concept, year)`)
- Wraps edgar-parser API (verified at impl start)

**New**: `risk_module/fmp/tools/transcript_kpi_fetcher.py` (per TB.D8)
- `fetch_kpi_from_transcripts(ticker, kpi_key, kpi_definition, fiscal_year) -> (value, raw_payload, retrieved_at)`
- Uses FMP earnings transcripts (via existing `fmp.fetch_raw("earning_call_transcript", ...)`) + regex matching against `kpi_definition.extraction.pattern_hints`
- Internal cache (24h TTL)

**New**: `risk_module/utils/timeseries_collector.py` (per TB.D5)
- `collect_timeseries(focal_ticker, peers, kpi_registry, manifest, years, *, existing_sources=None) -> dict` — returns the time-series + sources list

**New**: `risk_module/utils/kpi_registry_loader.py`
- `load_kpi_registry(industry_key: str) -> KPIRegistry` (Pydantic model)
- Lazy cross-repo loader from AI-excel-addin's `config/industry_kpis/`

**Modified**: `risk_module/mcp_tools/industry.py`
- When flag on AND `industry_key != "unknown"`: call Track B's time-series collector and add `operating_comparison` to top-level output
- When `industry_key == "unknown"`: omit `operating_comparison` field entirely (per TB.D6)
- Source registration: combine Track A and Track B sources into one bundle

**New tests**:
- `tests/fmp/test_edgar_concept_fetcher.py` — wrapper coverage
- `tests/fmp/test_transcript_kpi_fetcher.py` — pattern-match coverage
- `tests/fmp/test_manifest_source_dispatcher_kpi_kinds.py` — extends Track A's dispatcher tests with `kpi` / `edgar_concept` / `transcript_kpi` branches
- `tests/utils/test_timeseries_collector.py` — orchestrator tests
- `tests/utils/test_kpi_registry_loader.py` — registry validation
- `tests/mcp_tools/test_industry_v1_2_operating_comps.py` — end-to-end with HR-Payroll ticker; verifies `operating_comparison` field present, multi-year series populated, sources merged

### AI-excel-addin (registry + manifest)

**New**: `AI-excel-addin/config/industry_kpis/hr_payroll.yaml` (KPI registry)
**New**: `AI-excel-addin/config/comps_templates/operating_comps_hr_payroll_v1.yaml` (manifest)
**New**: `AI-excel-addin/config/comps_templates/operating_comps_hr_payroll_v1.fixture.csv`
**New**: `AI-excel-addin/schema/kpi_registry.py` (Pydantic model for `industry_kpis/*.yaml`)
**Modified**: `AI-excel-addin/schema/comps_template.py` — add `kind: kpi` to `CompsManifestSourceBinding`'s `kind` Literal (additive)

### Out of scope (deferred)

- Grocers + third reference industry (v1.1 — zero code changes per TB.D10)
- Renderer support for `operating_comparison` shape (downstream)
- Persistence-to-Thesis integration (same OOS as Track A — future follow-up plan)
- Cross-industry KPI comparability (operating comps are industry-keyed by design)
- Real-time KPI freshness on filing publish (existing TTL-cache pattern is sufficient for v1)

---

## 5. Tests

| Test file | Coverage |
|---|---|
| `tests/fmp/test_edgar_concept_fetcher.py` (new) | Mocked edgar-parser API: returns concept value for ticker/year; cache hit/miss; missing concept returns None; cache key correctness |
| `tests/fmp/test_transcript_kpi_fetcher.py` (new) | Mocked FMP transcripts: pattern matching against `pattern_hints` from KPI registry; multiple matches → first wins; no match → None; cache hit/miss |
| `tests/fmp/test_manifest_source_dispatcher_kpi_kinds.py` (new) | Three new `kind` branches: kpi indirection, edgar_concept, transcript_kpi; SourceRecord construction (type="filing", "transcript", "other"); error handling per kind |
| `tests/utils/test_timeseries_collector.py` (new) | Multi-year × multi-peer × multi-KPI matrix; median_series computation; sources accumulator; partial failures (one peer-year fetches null) |
| `tests/utils/test_kpi_registry_loader.py` (new) | Validates Pydantic schema; rejects malformed registry (missing required fields); lazy import from AI-excel-addin |
| `tests/mcp_tools/test_industry_v1_2_operating_comps.py` (new) | End-to-end with HR-Payroll ticker (e.g., PCTY): flag on + industry_key="hr_payroll" → `operating_comparison` present with `years`, `metric_groups`, all KPIs from registry; flag on + industry_key="unknown" (e.g., AAPL) → `operating_comparison` field absent; flag off → no v1.2 fields at all |

~30-40 test cases across 6 new files. Existing Track A tests must continue to pass (operating_comparison addition is additive at top level).

---

## 6. Cross-cutting concerns

### 6.1 Sources from EDGAR + transcripts
SourceRecord type per Track 0 R4 enum:
- EDGAR concept fetch → `type: "filing"`, `source_id: <accession_number>`, `endpoint_or_filing_id: f"{form}_{fy}_{concept}"`, `key_fields: {symbol, form, fy, concept}`, `text: ""` (concept value, not narrative)
- Transcript KPI fetch → `type: "transcript"`, `source_id: f"fmp_transcripts:{ticker}:{quarter}"`, `endpoint_or_filing_id: "earning_call_transcript"`, `key_fields: {symbol, quarter, kpi_key}`, `text: <matched pattern excerpt>` (the literal sentence containing the KPI value — useful for human review)

### 6.2 Caching (per TB.D8)
- EDGAR concept cache: 24h TTL per `(ticker, concept, fiscal_year)`
- Transcript KPI cache: 24h TTL per `(ticker, kpi_key, fiscal_year)`
- Both follow Track A's TTLCache pattern with `retrieved_at` preserved on cache hit (so SourceRecord identity is stable)

### 6.3 Error handling
- `kind: edgar_concept` lookup fails / concept missing → cell value `None`, `source_refs: []`; metric still appears in section per `null_policy: "skip"`
- `kind: transcript_kpi` no pattern match → cell value `None`, `source_refs: []`
- KPI registry missing for a known industry_key → producer raises explicitly (registry coverage gap, fail-loud)
- `industry_key="unknown"` → operating_comparison omitted (NOT an error per TB.D6)

### 6.4 Logging
Same minimal pattern as Track A — `portfolio_logger.warning` only on fallback events (extraction failures, registry-missing, etc.). No per-call structured log.

### 6.5 Performance
Time-series collection is N peers × M KPIs × Y years dispatcher calls. For HR-Payroll v1: ~7 peers × ~10 KPIs × ~8 years ≈ 560 dispatcher calls. With 24h cache and per-source ThreadPoolExecutor (existing pattern from Track A), first call is ~5-10s; cached calls are sub-second. Acceptable for v1.

---

## 7. Out of scope

- **Operating-comps for industries beyond HR-Payroll** — Grocers + third reference industry are v1.1 (zero code changes per TB.D10; just new yaml files)
- **Renderer for `operating_comparison`** — downstream; existing `HandoffSectionRenderer.tsx` needs new branch (separate plan)
- **Persistence-to-Thesis** — same OOS as Track A; future follow-up integrates producer into handoff assembly path
- **Per-quarter granularity** — v1 is annual time-series only; quarterly is v2 if needed
- **Cross-industry KPI mapping** (e.g., comparing HR-Payroll's "Clients" to Retail's "Stores") — explicitly out per framework
- **LLM-based KPI extraction** — v1 uses regex pattern matching from `pattern_hints`; LLM extraction is a v1.1+ enhancement
- **EDGAR concept extraction beyond reported us-gaap concepts** — v1 uses concepts already covered by the EDGAR parser; non-standardized custom concepts are v2
- **Real-time KPI freshness on filing publish** — TTL-based cache only; no event-driven refresh

---

## 8. Rollout sequence

1. **Phase 1**: ship `kpi_registry.py` (Pydantic) + `kpi_registry_loader.py` + tests (no behavioral change)
2. **Phase 2**: ship HR-Payroll yaml registry + manifest + fixture in AI-excel-addin (data-only commit)
3. **Phase 3**: ship `edgar_concept_fetcher.py` + `transcript_kpi_fetcher.py` + their tests (helper modules)
4. **Phase 4**: extend `manifest_source_dispatcher.py` with three new `kind` branches + tests
5. **Phase 5**: ship `timeseries_collector.py` + tests (orchestration helper)
6. **Phase 6**: extend `mcp_tools/industry.py` to emit `operating_comparison` when flag on + industry known + integration tests. Flag-off shipping.

Phases 1-5 land flag-off — no behavioral change. Phase 6 wires it together; flag stays off in production until renderer + skill consumers are ready.

---

## 9. Open questions (deferrable to impl)

1. **EDGAR parser API signature** — verify at impl start (`fetch_concept` exact signature, fiscal_year semantics, error contract). If the parser doesn't expose per-concept-per-year, Track B's wrapper builds it.
2. **FMP earnings-transcript endpoint** — verify cost ($/call) and rate limits; cache aggressively if expensive.
3. **Pattern-match disambiguation** — when multiple candidate sentences match a KPI's `pattern_hints`, take the first? Highest-confidence? v1: first match. Document.
4. **HR-Payroll KPI list** — confirmed from editorial template: Clients, Retention, Revenue/Client, S&M %, R&D %, CapEx %, EBITDA margin, FCF margin, FCF conversion. Final list per the manifest yaml committed in Phase 2.
5. **Year range default** — manifest specifies `years_back: 8` or explicit `[2018, ..., 2025]`? Editorial template uses fixed range. Lean: `years_back: 8` from current FY for forward-stable manifests.

---

## 10. Summary

Track B closes the canonical comps framework by adding the operating-comps producer:

- **5 new modules** in risk_module (`edgar_concept_fetcher`, `transcript_kpi_fetcher`, `timeseries_collector`, `kpi_registry_loader`, modified dispatcher)
- **1 modified module** in risk_module (`mcp_tools/industry.py` — additive `operating_comparison` field at flag-on)
- **3 new yaml/csv files** in AI-excel-addin (HR-Payroll registry + manifest + fixture)
- **1 new Pydantic schema** in AI-excel-addin (`kpi_registry.py`)
- **1 modified schema** in AI-excel-addin (`comps_template.py` — add `kind: kpi` to source-binding Literal)
- **6 new test files** (~30-40 cases)
- **0 new patch ops** (Track 0 shipped them; persistence-to-Thesis OOS)
- **0 schema changes to thesis_shared_slice** (Track 0 already shipped `OperatingComparison`/`TimeseriesGroup`/`TimeseriesMetric`)

After Track B merges (flag-off), the canonical comps framework is **complete for v1**. Flag-on integration is a separate downstream gate (renderer + skill consumers ready). v1.1 adds Grocers + a third reference industry as data-only commits.

---
