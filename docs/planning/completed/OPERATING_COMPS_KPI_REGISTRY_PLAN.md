# Track B — Operating Comps + Per-Industry KPI Registry (Canonical Comps Framework)

**Status**: DRAFT R7 — implementation plan for Track B of the canonical comps framework.
**Created**: 2026-05-07. **Revised**: 2026-05-07 (R1: 5P1+4P2 → R2: 3 blockers → R3: 2P1 → R4: 2P1 → R5: 1P1+1P2 → R6: 3 doc-consistency → R7: 2 doc-consistency; see §11 changelog).
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 (Codex PASS) — see §5 for Track B scope.
**Prerequisites**:
- Track 0 (`SCHEMA_AND_PATCH_OPS_PLAN.md` R4 PASS) — SHIPPED on AI-excel-addin commit `7ce654d`. Provides `OperatingComparison`, `TimeseriesGroup`, `TimeseriesMetric` schemas + `industry_resolver.resolve_industry_key()` + source registry.
- Track C (`EDITORIAL_PEER_SET_PLAN.md` R4 PASS) — SHIPPED on risk_module commit `24af19d5`. Provides `resolve_peer_universe()` helper.
- Track A (`INDUSTRY_COMPS_ARTIFACT_PLAN.md` R5 PASS) — SHIPPED on risk_module commit `ff3ff50f` + AI-excel-addin commit `85543e4`. Provides `manifest_source_dispatcher.py` (extensible by `kind`), `comps_aggregator.py`, dual-write + flag pattern.

**Authoritative code references** (verified by file read 2026-05-07):
- `AI-excel-addin/schema/thesis_shared_slice.py:455-472` — `TimeseriesMetric`, `TimeseriesGroup`, `OperatingComparison` types
- `AI-excel-addin/schema/thesis_shared_slice.py:510` — `IndustryAnalysis.operating_comparison: OperatingComparison | None = None`
- `fmp/tools/manifest_source_dispatcher.py:11-99` — Track A's dispatcher; `DispatchResult(value, source_endpoint: str | None)`; `kind: fmp_endpoint` + `kind: derived` handlers (Track B extends with three new branches)
- `utils/comps_aggregator.py` — Track A's median/mean aggregator (Track B reuses for `median_series`)
- `mcp_tools/industry.py:115-168` — Track A's manifest-driven dual-write producer; flag literal `INDUSTRY_ANALYSIS_V1_2_ENABLED == "true"` (case-insensitive); source registration happens here, NOT in dispatcher (Track B extends to also emit `operating_comparison`)
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
| **Manifest schema can't currently express year range** — `CompsTemplateManifest` has no `years` / `years_back`, and `_ContractModel` is `extra="forbid"` (`thesis_shared_slice.py:66-68`) | `comps_template.py:50-56` | **Schema must extend additively** in AI-excel-addin: `years: list[int] \| None = None` + `years_back: int \| None = None`, with model-level validator requiring exactly one when `template_kind == "operating_comps"`. See TB.D3. |
| **Source-binding `kind` Literal already allows `edgar_concept` + `transcript_kpi`** (Track 0 anticipated); only `kpi` is missing | `comps_template.py:11` | AI-excel-addin schema change is small: add `"kpi"` to the Literal (the `kpi_key: str \| None` field is already present at `comps_template.py:15`). See TB.D4. |
| Track A's dispatcher takes `(binding, fmp_response_bundle, focal_ticker, *, resolved_metrics, metric_key, resolving)` and returns `DispatchResult(value, source_endpoint: str \| None)` per `kind`. `SourceRecord` registration happens at producer level (`mcp_tools/industry.py:168`), NOT in dispatcher. | `manifest_source_dispatcher.py:11-99` | Track B's three new kinds (`kpi`, `edgar_concept`, `transcript_kpi`) follow the same `(value, endpoint_marker)` contract; producer constructs `SourceRecord` (with `type="filing"` / `"transcript"` / `"other"` per kind) using endpoint marker + per-kind metadata. See TB.D4 + §6.1. |
| **Dispatcher signature has no `fiscal_year` param** — operates on a TTM bundle (Track A's `_peer_metric_snapshot_cache` populates the bundle once per peer for the as-of moment) | `manifest_source_dispatcher.py:58-66`; producer at `mcp_tools/industry.py:156` | Track B needs annual data per year. **Additive extension**: add `fiscal_year: int \| None = None` to dispatcher signature (default None preserves Track A TTM behavior). Track B's `timeseries_collector` builds a separate **annual** FMP bundle per (peer, year) and passes `fiscal_year=year` so the dispatcher's annual branches read the right rows. See TB.D5. |
| Track A's producer at `mcp_tools/industry.py` returns flat top-level dict; flag-on adds `peers, sections, industry_key, ...` | `mcp_tools/industry.py` (Track A) | Track B further extends top-level: add `operating_comparison` field when flag on AND industry_key is known AND a registry exists for that industry. Strictly additive. |
| `resolve_industry_key(fmp_profile)` (Track 0) returns reference industry or `"unknown"` | `AI-excel-addin/schema/industry_resolver.py` | Track B short-circuits when key is unknown — does not produce operating_comparison; keeps Track A's snapshot artifact untouched. **Same silent-skip behavior** when known industry has no registry yet (see TB.D6). |
| EDGAR parser exposes `get_metric(ticker, year, quarter, metric_name, full_year_mode=False, source="auto", date_type=None) -> dict` (NOT a "us-gaap concept by fiscal year" API) | `/Users/henrychien/Documents/Jupyter/edgar-parser/edgar_parser/tools.py:722` | Track B's wrapper passes the concept name as `metric_name`, uses `quarter=None` + `full_year_mode=True` for annual data, and pulls `value` + accession metadata from the response. Exact return shape verified at impl start. See TB.D8. |
| FMP earnings transcripts already have a wrapper — `get_earnings_transcript(symbol, year, quarter, ...)` with built-in cache | `fmp/tools/transcripts.py:1032` | Track B's transcript-KPI fetcher CALLS this wrapper (not raw `fmp.fetch_raw("earning_call_transcript", ...)`). For each fiscal year, query Q1–Q4 with `format="full"`, regex-match `pattern_hints` from the KPI registry. See TB.D8. |
| Editorial operating-comps templates exist (Grocers, HR-Payroll-shaped SheetsFinance) | (Google Drive) | Reference industry for v1: **HR-Payroll** — KPIs: Clients, % client growth, Retention, Revenue per client, S&M as % of sales, R&D as % of sales, CapEx as % of revenue, EBITDA margin, FCF margin (per editorial template) |

**Gap summary**: Track B has **zero `thesis_shared_slice` schema work** (Track 0 shipped `OperatingComparison`/`TimeseriesGroup`/`TimeseriesMetric`), zero peer-resolver work (Track C shipped it), and the dispatcher pattern is established (Track A shipped it). What's new splits across two repos:

- **In `AI-excel-addin`**: schema extensions (one-token additive `kind: "kpi"` on `CompsManifestSourceBinding`; additive `years` / `years_back` on `CompsTemplateManifest` per TB.D3 / TB.D4); new `KPIRegistry` Pydantic for `industry_kpis/*.yaml`; the per-industry KPI registry yaml + per-industry operating-comps manifest yaml + fixture CSV (HR-Payroll v1).
- **In `risk_module`**: the EDGAR/transcript dispatcher kinds (with `kind: kpi` indirection), the per-(peer, year) annual FMP bundle helper, the time-series collector, the KPI registry loader, and the producer wire-up that emits `operating_comparison` when flag on + industry known + registry exists.

---

## 3. Locked design decisions

### TB.D1. Reference industry for v1: HR-Payroll
First per-industry KPI registry + manifest target HR-Payroll (PCTY, PAYC, PYCR, CDAY, ADP, PAYX, WDAY) — best documented in editorial templates. KPIs include Clients, Retention, Rev/Client, S&M %, R&D %, CapEx %, EBITDA margin, FCF margin. v1 ships HR-Payroll only; Grocers + a third reference industry follow in v1.1.

### TB.D2. KPI registry yaml at `config/industry_kpis/<industry_key>.yaml` (per Track 0 D4)
Definitions only — no `peer_universe` (per Track 0 / framework D5). Each KPI has **exactly one** extraction kind in v1 (no fallback chain — additive in v1.1+ if needed).

Schema:
```yaml
industry_key: hr_payroll
display_name: HR / Payroll
template_manifest_id: operating_comps_hr_payroll_v1
kpis:
  # KPIs sourced from earnings transcripts (regex pattern-match)
  - key: clients
    label: Clients
    units: count
    definition: "Total customers paying for payroll/HCM service"
    aliases: [customers, subscribers, merchants]
    extraction:
      kind: transcript_kpi              # one of: transcript_kpi, edgar_concept, derived
      pattern_hints: ["client count", "we serve N customers"]
  - key: retention
    label: Retention
    units: percent
    definition: "Annual revenue retention rate"
    extraction:
      kind: transcript_kpi
      pattern_hints: ["retention rate", "% retention"]
  # KPIs sourced from EDGAR (us-gaap concept)
  - key: revenue
    label: Revenue
    units: usd
    extraction:
      kind: edgar_concept
      concept_name: Revenues             # us-gaap concept passed to edgar_parser.get_metric
  # KPIs derived from other KPIs in the same registry (per-year)
  - key: revenue_per_client
    label: Revenue per client
    units: usd
    extraction:
      kind: derived
      formula: "revenue / clients"       # AST-validated; references other KPI keys
```

**`extraction.kind` Literal** (Pydantic): `transcript_kpi | edgar_concept | derived`. The dispatcher's `kind: kpi` indirection looks up `kpi_def.extraction.kind` and constructs a synthetic binding of that exact kind:
- `transcript_kpi` → synthetic binding with `kpi_key=<this kpi's key>`; dispatcher's `transcript_kpi` branch reads `pattern_hints` from the registry by `kpi_key`.
- `edgar_concept` → synthetic binding with `edgar_concept=<extraction.concept_name>`; dispatcher's `edgar_concept` branch fetches that us-gaap concept.
- `derived` → synthetic binding with `derived_formula=<extraction.formula>`; dispatcher's existing `derived` branch (Track A, unchanged) evaluates against `resolved_metrics` (which contains earlier per-year KPI cells).

`financial_metrics` (universal financials referenced by manifest, separate from operational KPIs):
```yaml
financial_metrics:
  - revenue
  - sales_growth
  - sm_expense
  # ...
```
These are NOT keyed in the registry — the manifest references them via `kind: fmp_endpoint` directly (Track A pattern, now annual-aware per TB.D5).

The KPI registry is a **content** layer (per-industry KPI definitions); the manifest is a **structure** layer (per-industry rendering shape). They're separate files.

**v1 fallback semantics**: none. A KPI has one extraction kind; if the fetcher returns None for a (ticker, year), the cell is None. v1.1 may extend `extraction` to a list with explicit fallback ordering — additive change.

### TB.D3. Per-industry operating-comps manifest at `config/comps_templates/operating_comps_<industry_key>_v1.yaml`
Mirrors Track 0's manifest shape but for time-series with `template_kind: "operating_comps"`. Sections, metrics, source bindings, ordering — same structure as `industry_comps_generic_v1.yaml`. Source bindings reference KPI keys from the registry via new `kind: kpi` (looks up KPI definition from registry, then dispatches per the KPI's `extraction.kind` per TB.D2 — `transcript_kpi`, `edgar_concept`, or `derived`).

**Schema extension required (additive)**: `CompsTemplateManifest` (`AI-excel-addin/schema/comps_template.py:50`) currently has no field for year range and `_ContractModel` is `extra="forbid"`. Add:
```python
years: list[int] | None = None
years_back: int | None = None  # if set, resolved at producer time as last N completed FYs
```
Plus a model-level validator: when `template_kind == "operating_comps"`, exactly one of `years` / `years_back` must be set. When both are None or both are set, raise. Track A (`template_kind == "industry_comps"`) is untouched — TTM-only.

Companion fixture CSV at `<manifest_id>.fixture.csv` per Track 0 §7.7.

### TB.D4. Dispatcher extends with `kind: edgar_concept`, `kind: transcript_kpi`, and `kind: kpi`; DispatchResult gains `source_meta`
**Schema-side**: `CompsManifestSourceBinding.kind` Literal already allows `edgar_concept` + `transcript_kpi` (Track 0 anticipated; verified at `comps_template.py:11`). Only `"kpi"` needs to be added to the Literal (the carrier field `kpi_key: str | None` is already present at `comps_template.py:15`).

**Dispatcher-side — `DispatchResult` extension (additive third field)**: today the NamedTuple is `(value, source_endpoint: str | None)` (`manifest_source_dispatcher.py:11-13`). Track B extends it to `(value, source_endpoint: str | None, source_meta: dict | None)`. Track A branches (`fmp_endpoint`, `derived`) return `source_meta=None` → producer's existing TTM SourceRecord construction at `mcp_tools/industry.py:337-346` is unchanged (it builds source_id + key_fields from the endpoint marker alone). Track B branches return `source_meta` populated with kind-specific keys so the producer can construct accession-scoped EDGAR / quarter-scoped transcript SourceRecords without round-tripping through the dispatcher again.

`source_meta` schema per kind (Track B):
- `edgar_concept` → `{"accession": str | None, "form": str | None, "fiscal_year": int, "concept": str, "retrieved_at": str, "raw_payload": dict}` (accession + form pulled from `get_metric` response's `source` metadata; raw payload preserved for audit and future spans extraction)
- `transcript_kpi` → `{"quarter": int, "fiscal_year": int, "kpi_key": str, "matched_excerpt": str, "retrieved_at": str}` (quarter is the Q where the first match was found; matched_excerpt is the literal sentence containing the KPI value)
- `kpi` → forwards `source_meta` from the resolved sub-kind (transcript_kpi or edgar_concept) unchanged

**Dispatcher signature additions (kw-only, additive)**: in addition to `fiscal_year: int | None = None` (TB.D5), `dispatch_source_binding` gains `kpi_registry: KPIRegistry | None = None`. The registry is loaded once by the collector (TB.D5) and passed on every Track B dispatch call. Track A callers pass None — `fmp_endpoint` and `derived` branches don't read it.

**Three new branches in `dispatch_source_binding`** (per TB.D2, KPI extraction is deterministic — single kind per KPI, no fallback list in v1):
- `kind: kpi` — indirection layer: looks up the KPI in `kpi_registry` by `binding.kpi_key`. Reads `kpi_def.extraction.kind` (one of `transcript_kpi`, `edgar_concept`, `derived` per the Literal in TB.D2) and constructs the corresponding synthetic binding:
  - `transcript_kpi` → synthetic `CompsManifestSourceBinding(kind="transcript_kpi", kpi_key=binding.kpi_key)`
  - `edgar_concept` → synthetic `CompsManifestSourceBinding(kind="edgar_concept", edgar_concept=kpi_def.extraction.concept_name)`
  - `derived` → synthetic `CompsManifestSourceBinding(kind="derived", derived_formula=kpi_def.extraction.formula)`
  Then RECURSIVELY calls `dispatch_source_binding(synthetic_binding, fmp_response_bundle, focal_ticker, resolved_metrics=resolved_metrics, metric_key=metric_key, resolving=resolving, fiscal_year=fiscal_year, kpi_registry=kpi_registry)` — passing the SAME `fiscal_year` and `kpi_registry` through. `source_endpoint` and `source_meta` are forwarded from the resolved sub-call. Recursion is bounded (registry KPIs cannot have `extraction.kind == "kpi"` — the Literal forbids it; one-level indirection only). Raises if `kpi_registry is None`, `kpi_key` not found, or registry KPI has malformed `extraction` (e.g., `transcript_kpi` without `pattern_hints`, `edgar_concept` without `concept_name`).
- `kind: edgar_concept` — reads `binding.edgar_concept` (the us-gaap concept name); calls `edgar_concept_fetcher.fetch_concept(ticker, concept, fiscal_year)`; `source_endpoint = f"edgar_concept:{concept}"`; `source_meta` populated with accession/form/fiscal_year/concept/retrieved_at/raw_payload. Does NOT use `kpi_registry` directly. Raises if `fiscal_year is None`.
- `kind: transcript_kpi` — reads `binding.kpi_key`; looks up `kpi_definition` from `kpi_registry`; reads `kpi_definition.extraction.pattern_hints`; calls `transcript_kpi_fetcher.fetch_kpi_from_transcripts(ticker, kpi_key, kpi_definition, fiscal_year)`; `source_endpoint = f"transcript_kpi:{kpi_key}"`; `source_meta` populated with quarter/fiscal_year/kpi_key/matched_excerpt/retrieved_at. Raises if `kpi_registry is None`, `kpi_key` not found, `fiscal_year is None`, or `pattern_hints` missing.

The existing `kind: derived` branch (Track A, unchanged) handles per-year derived KPIs because the collector keeps a shared `resolved_metrics` dict per (ticker, year) across the metric loop (per TB.D5 below) — `derived_formula="revenue / clients"` resolves against earlier-loop per-year KPI cells.

**Why dispatcher-resolved (not collector-resolved)**: the collector stays a thin orchestrator (year/peer/metric loop). Putting `kind: kpi` resolution in the dispatcher keeps registry lookup in one place and keeps the `dispatch_source_binding` contract closed over the binding/registry pair. The collector mutates nothing — it loads the registry once and passes it through.

**Existing-callers analysis**: dispatcher callers grepped at R2 (`mcp_tools/industry.py` + tests only). Both new kw-only params are defaulted to None, so the existing call sites in Track A (which use positional binding/bundle/focal_ticker + the existing kw-only `resolved_metrics`/`metric_key`/`resolving`) are unchanged. Track A unpacks the result by index `[0]` / `[1]`; adding a third NamedTuple field is backward-compatible at the unpack site. The producer's source-construction path adds a branch: when `source_meta` is non-None, build the SourceRecord from the meta dict per §6.1 instead of reusing `_source_id_for_endpoint`'s TTM template.

### TB.D5. Time-series orchestrator: new `utils/timeseries_collector.py` + new `fmp/tools/peer_annual_bundle.py` + dispatcher signature extension
**Dispatcher signature (additive)**: extend `dispatch_source_binding` in `fmp/tools/manifest_source_dispatcher.py` to accept `fiscal_year: int | None = None` (default None preserves Track A TTM behavior bit-identically). Existing `kind: fmp_endpoint` and `kind: derived` ignore the param; new branches use it.

**Per-year annual FMP bundle — new helper module**: Track A's `_peer_metric_snapshot_cache` (in `mcp_tools/industry.py`) populates a TTM bundle once per peer for the as-of moment, and the SourceRecord template at `mcp_tools/industry.py:337-346` hardcodes `period: "ttm"` in `source_id` and `key_fields`. Track B cannot reuse that path for annual data. Introduce a parallel helper:

**New file `fmp/tools/peer_annual_bundle.py`** — function:
```python
def fetch_peer_annual_bundle(
    ticker: str,
    fiscal_year: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Returns (annual_bundle, retrieved_at_by_endpoint).

    annual_bundle keys mirror Track A's TTM bundle keys but for period='annual':
        income_statement, balance_sheet, cash_flow_statement, key_metrics, ratios.
    Each row filtered to the row matching `fiscal_year` (one row per endpoint).
    retrieved_at_by_endpoint maps each fetched endpoint name to its ISO timestamp.
    """
```
Module-level cache at `(ticker, fiscal_year)` grain (24h TTL) parallel to Track A's `_peer_metric_snapshot_cache` pattern. Each FMP call uses `period="annual"` parameter (verified against `fmp.fetch` annual semantics at impl start).

**Producer-level annual SourceRecord construction**: introduce a parallel helper next to `mcp_tools/industry.py::_source_id_for_endpoint` (Track A's TTM template) — call it `_source_id_for_annual_endpoint(...)`. Same shape as Track A's TTM helper but with:
- `source_id=f"fmp:{endpoint}:{ticker}:annual:{fiscal_year}"`
- `key_fields={"symbol": ticker, "period": "annual", "fiscal_year": fiscal_year}`
- `retrieved_at` from the new bundle's per-endpoint timestamp dict
- `type="other"`, `provider="fmp"`, `endpoint_or_filing_id=endpoint` unchanged

The annual SourceRecord helper is invoked by the producer when it sees a `DispatchResult` with `source_endpoint != None` AND `source_meta is None` AND the call was made with `fiscal_year != None` (the annual FMP path). EDGAR/transcript SourceRecords (with `source_meta != None`) take the §6.1 paths instead.

**Per-year derived KPI ordering**: the collector keeps a `resolved_metrics_by_ticker_by_year: dict[str, dict[int, dict[str, Any]]]` — analogue to Track A's `resolved_metrics_by_ticker` at `mcp_tools/industry.py:142-144`, but with an extra year dimension. For each (ticker, year), a SHARED `resolved_metrics` dict accumulates across the metric loop within that year, so `kind: derived` (e.g., `revenue_per_client = revenue / clients`) can reference earlier-resolved per-year cells. `resolving` set is fresh per-metric-dispatch (matches Track A semantics); the dispatcher's existing single-pass cycle detection (`manifest_source_dispatcher.py:84-97`) handles base-before-derived ordering within a year. **No cross-year derivation in v1** (e.g., 2y EPS CAGR is computed at presentation time from per-year cells, not as a single derived metric — and the collector does not write across `[ticker][year_a]` from `[ticker][year_b]`'s loop).

**Pure orchestration**: `collect_timeseries(focal_ticker, peers, kpi_registry, manifest, years, *, existing_sources=None) -> dict`:
1. Resolves year range (manifest's `years` literal list, or `years_back` → last N completed FYs from `last_reported_fiscal_date` metadata)
2. Initializes `resolved_metrics_by_ticker_by_year: dict[str, dict[int, dict[str, Any]]]` — one inner dict per (ticker, year), shared across the metric loop within that year so derived KPIs resolve.
3. For each peer × year, fetches the annual FMP bundle via `peer_annual_bundle.fetch_peer_annual_bundle(peer, year)` (cached).
4. For each metric in manifest order (within a year, for a peer), calls dispatcher with:
   ```python
   dispatch_source_binding(
       binding,
       annual_bundle,
       peer,
       fiscal_year=year,
       kpi_registry=kpi_registry,
       resolved_metrics=resolved_metrics_by_ticker_by_year[peer][year],  # SHARED across loop
       metric_key=metric.key,
       resolving=set(),                                                    # fresh per dispatch
   )
   ```
   After the call, write `resolved_metrics_by_ticker_by_year[peer][year][metric.key] = normalized_value` (mirrors Track A's `resolved_metrics_by_ticker[ticker][metric.key] = value` at `mcp_tools/industry.py:166`).
5. Aggregates results into `series: dict[ticker, dict[year, CompMetricCell]]`.
6. Computes `median_series` per year via Track A's `comps_aggregator` (one aggregation call per (metric, year)).

The collector loads `kpi_registry` once (passed in by the producer per TB.D6 — it's already loaded by the producer to decide whether to invoke Track B at all) and threads it through every dispatch call. The registry stays read-only — the dispatcher's `kind: kpi` branch resolves `kpi_key` → KPI def via lookup, never mutates.

Pure function: testable without network calls via dispatcher + bundle-fetcher mocking.

### TB.D6. `industry_key="unknown"` OR no registry → silent-skip operating_comparison
Per Track 0 D9 + framework: when `resolve_industry_key()` returns `"unknown"`, Track B does NOT produce `operating_comparison`. Producer's flag-on output omits the `operating_comparison` field. Track A's snapshot artifact (`peer_comparison.sections`) is unaffected — that uses the generic manifest and works for any ticker.

**Tickers with known industry but no KPI registry yet** (extension industries beyond HR-Payroll in v1): same silent-skip behavior. The single MCP tool `industry_peer_comparison()` serves both Track A AND Track B output — fail-loud here would break Track A's snapshot for any non-HR-Payroll known industry, which is unacceptable. The producer logs a `portfolio_logger.warning("operating_comps registry missing for industry_key=...; skipping operating_comparison")` and continues with Track A output only.

Fail-loud is reserved for an explicit operating-comps-required entry point, which v1 does NOT expose. If a future caller needs hard-required operating comps (e.g., a Hank skill that promises operating-comps deliverables), it adds a separate flag/parameter and asserts registry presence at its own boundary — not at this producer.

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

### TB.D8. EDGAR + transcript extraction wrappers — grounded against verified APIs
Track B introduces two thin extraction wrappers, both calling EXISTING APIs (verified during R0→R1 review):

**`fmp/tools/edgar_concept_fetcher.py`** (new) — function `fetch_concept(ticker, concept_name, fiscal_year) -> tuple[float | None, dict, str]` returning `(value, raw_payload, retrieved_at)`.
- Calls `edgar_parser.tools.get_metric(ticker, year=fiscal_year, quarter=None, metric_name=concept_name, full_year_mode=True, source="auto")` (signature verified at `/Users/henrychien/Documents/Jupyter/edgar-parser/edgar_parser/tools.py:722`).
- The parser returns a dict with `status`, `matches: list[dict]` (with `current_value`, `metric`, etc.), and `source` metadata. Wrapper extracts the first match's `current_value` as the float, preserves the full payload for audit, and reads accession from `source` metadata for SourceRecord construction (exact accession field path confirmed at impl start).
- 24h TTL cache keyed by `(ticker, concept, fiscal_year)`.
- `quarter=None` + `full_year_mode=True` is the parser's documented annual-data mode; verify behavior in fixture-based test before relying on this combo for production data.

**`fmp/tools/transcript_kpi_fetcher.py`** (new) — function `fetch_kpi_from_transcripts(ticker, kpi_key, kpi_definition, fiscal_year) -> tuple[float | None, dict, str]` returning `(value, raw_payload, retrieved_at)`.
- Iterates Q1–Q4 calling existing wrapper `fmp.tools.transcripts.get_earnings_transcript(symbol=ticker, year=fiscal_year, quarter=q, format="full")` (signature verified at `fmp/tools/transcripts.py:1032`). The wrapper has its own per-(symbol, year, quarter) JSON cache, so we don't duplicate caching at the per-quarter grain.
- Module-level cache at the (ticker, kpi_key, fiscal_year) grain (24h TTL) avoids re-running pattern matching across the 4 quarters on cache hit.
- Pattern matching: regex over the joined transcript text using `kpi_definition.extraction.pattern_hints`. v1 picks first match (per §9 Q3); the matched sentence excerpt becomes the SourceRecord's `text` (§6.1). Returns None if no match across all 4 quarters.

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

**Modified**: `fmp/tools/manifest_source_dispatcher.py`
- Extend `DispatchResult` NamedTuple from `(value, source_endpoint)` to `(value, source_endpoint, source_meta: dict | None)` (additive third field — backward compatible because Track A unpack sites use index access). Track A branches return `source_meta=None`.
- Add kw-only params to `dispatch_source_binding` (both default None — Track A unaffected): `fiscal_year: int | None = None` (TB.D5) and `kpi_registry: KPIRegistry | None = None` (TB.D4)
- Add three new `kind` branches: `kpi`, `edgar_concept`, `transcript_kpi`
- All three return `DispatchResult(value, source_endpoint, source_meta)` per TB.D4 — SourceRecord construction stays at producer level (`mcp_tools/industry.py:168`) but uses `source_meta` for EDGAR/transcript shapes
- `kpi` branch: indirection layer — looks up KPI def in `kpi_registry` by `binding.kpi_key`, reads `kpi_def.extraction.kind` (Literal `transcript_kpi | edgar_concept | derived` per TB.D2), constructs a synthetic `CompsManifestSourceBinding` of that kind (using `pattern_hints` / `concept_name` / `formula` per kind), RECURSES through `dispatch_source_binding` with the synthetic binding (passing the same `fiscal_year` and `kpi_registry`), forwards `source_meta` from the resolved sub-call
- `edgar_concept` branch: calls `edgar_concept_fetcher.fetch_concept(ticker, binding.edgar_concept, fiscal_year)`; `source_endpoint = f"edgar_concept:{concept}"`; `source_meta = {accession, form, fiscal_year, concept, retrieved_at, raw_payload}`
- `transcript_kpi` branch: looks up `kpi_definition` from `kpi_registry` by `binding.kpi_key`; calls `transcript_kpi_fetcher.fetch_kpi_from_transcripts(ticker, kpi_key, kpi_definition, fiscal_year)`; `source_endpoint = f"transcript_kpi:{kpi_key}"`; `source_meta = {quarter, fiscal_year, kpi_key, matched_excerpt, retrieved_at}`
- All three new branches raise on missing prerequisites: `fiscal_year is None` (all), `kpi_registry is None` (kpi + transcript_kpi), `kpi_key` absent from registry (kpi + transcript_kpi)

**New**: `fmp/tools/peer_annual_bundle.py` (per TB.D5)
- `fetch_peer_annual_bundle(ticker, fiscal_year) -> tuple[dict, dict]` returning (annual_bundle, retrieved_at_by_endpoint)
- Module-level cache at (ticker, fiscal_year) grain (24h TTL) parallel to Track A's TTM cache pattern
- Wraps annual variants of FMP income/balance/cashflow/key-metrics/ratios endpoints (period="annual")

**New**: `fmp/tools/edgar_concept_fetcher.py` (per TB.D8)
- `fetch_concept(ticker, concept_name, fiscal_year) -> tuple[float | None, dict, str]`
- Internal cache (24h TTL, key: `(ticker, concept, fiscal_year)`)
- Wraps `edgar_parser.tools.get_metric(...)` with `quarter=None`, `full_year_mode=True`

**New**: `fmp/tools/transcript_kpi_fetcher.py` (per TB.D8)
- `fetch_kpi_from_transcripts(ticker, kpi_key, kpi_definition, fiscal_year) -> tuple[float | None, dict, str]`
- Iterates Q1–Q4 via existing `fmp.tools.transcripts.get_earnings_transcript(symbol, year, quarter, format="full")` wrapper (preserves its built-in per-quarter JSON cache)
- Module-level cache at (ticker, kpi_key, fiscal_year) grain (24h TTL) avoids re-running pattern matching on cache hit
- Regex matching against `kpi_definition.extraction.pattern_hints`; first match wins (per §9 Q3); matched sentence excerpt returned for SourceRecord `text`

**New**: `utils/timeseries_collector.py` (per TB.D5)
- `collect_timeseries(focal_ticker, peers, kpi_registry, manifest, years, *, existing_sources=None) -> dict` — returns the time-series + sources list
- Builds an annual FMP bundle per (peer, fiscal_year) (period="annual", separate from Track A's TTM cache)
- Maintains `resolved_metrics_by_ticker_by_year: dict[str, dict[int, dict[str, Any]]]` with one inner dict per (ticker, year), **shared across the metric loop within that year** (analog of Track A's `resolved_metrics_by_ticker` at `mcp_tools/industry.py:142-144`); writes `[peer][year][metric.key] = normalized_value` after each dispatch call (mirrors Track A's `:166`); `resolving=set()` is fresh per dispatch call (matches Track A semantics)
- Uses Track A's `comps_aggregator` for per-year median/mean

**New**: `utils/kpi_registry_loader.py`
- `load_kpi_registry(industry_key: str) -> KPIRegistry | None` (returns Pydantic model, or `None` when no registry yaml exists for `industry_key` — silent-skip path in producer per TB.D6)
- Lazy cross-repo loader from AI-excel-addin's `config/industry_kpis/`

**Modified**: `mcp_tools/industry.py`
- When flag on AND `industry_key != "unknown"` AND registry exists: call Track B's time-series collector and add `operating_comparison` to top-level output
- When `industry_key == "unknown"` OR registry missing: omit `operating_comparison` field entirely (per TB.D6); for missing-registry path, log `portfolio_logger.warning`
- Source registration: combine Track A snapshot sources and Track B time-series sources into one top-level `sources` bundle
- Add new helper `_source_id_for_annual_endpoint(...)` parallel to existing `_source_id_for_endpoint` at line 323-349; same shape but with `source_id=f"fmp:{endpoint}:{ticker}:annual:{fiscal_year}"` and `key_fields={"symbol": ticker, "period": "annual", "fiscal_year": fiscal_year}` (per TB.D5)
- Add SourceRecord-construction branches for EDGAR (`source_meta` carries accession + form) and transcript (`source_meta` carries quarter + matched_excerpt) per §6.1 — invoked when `DispatchResult.source_meta` is non-None

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
**Modified**: `AI-excel-addin/schema/comps_template.py` (per TB.D3 + TB.D4):
  - `CompsManifestSourceBinding.kind` Literal: add `"kpi"` (the four existing values stay; `kpi_key: str | None` carrier field already present at line 15 — no new field needed)
  - `CompsTemplateManifest`: add `years: list[int] | None = None` and `years_back: int | None = None`
  - `_validate_manifest`: extend to require exactly one of `years` / `years_back` when `template_kind == "operating_comps"` (raise on both-set or both-None); industry_comps untouched

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
| `tests/fmp/test_manifest_source_dispatcher_kpi_kinds.py` (new) | Three new `kind` branches: kpi indirection (recurses into resolved sub-kind), edgar_concept, transcript_kpi. Asserts `DispatchResult.value` + `source_endpoint` marker + `source_meta` dict shape per kind; verifies recursion termination (kpi indirection's synthetic binding is never `kind=kpi`); error handling per kind (raises on missing `fiscal_year`, `kpi_registry`, `kpi_key not in registry`, malformed extraction). **SourceRecord construction is NOT tested here** — that's producer-level (covered by `tests/mcp_tools/test_industry_v1_2_operating_comps.py` integration test). |
| `tests/utils/test_timeseries_collector.py` (new) | Multi-year × multi-peer × multi-KPI matrix; median_series computation; sources accumulator; partial failures (one peer-year fetches null) |
| `tests/utils/test_kpi_registry_loader.py` (new) | Validates Pydantic schema; rejects malformed registry (missing required fields); lazy import from AI-excel-addin |
| `tests/mcp_tools/test_industry_v1_2_operating_comps.py` (new) | End-to-end with HR-Payroll ticker (e.g., PCTY): flag on + industry_key="hr_payroll" → `operating_comparison` present with `years`, `metric_groups`, all KPIs from registry; flag on + industry_key="unknown" (e.g., AAPL) → `operating_comparison` field absent; flag on + known-but-no-registry industry → `operating_comparison` field absent + warning logged (silent-skip per TB.D6); flag off → no v1.2 fields at all |

**AI-excel-addin schema/fixture tests** (per Codex P2-4 + TB.D3 + TB.D4) — split across rollout phases per §8 ordering:

**Phase 1 (schema-only, inline fixtures, NO HR-Payroll yaml dependency)**:
| Test file | Coverage |
|---|---|
| `AI-excel-addin/tests/schema/test_comps_template_operating_comps.py` (new) | `CompsTemplateManifest` with `template_kind="operating_comps"`: requires exactly one of `years` / `years_back` (both-set raises; both-None raises); `industry_key` still required (existing); `kind: "kpi"` accepted in `CompsManifestSourceBinding`; industry_comps templates unaffected by new fields. **Inline manifest dicts only**, no yaml file load. |
| `AI-excel-addin/tests/schema/test_kpi_registry.py` (new) | `KPIRegistry` Pydantic schema validation with **inline dict fixtures only**: required fields (key/label/units/definition); aliases optional; `extraction.kind` Literal validation (transcript_kpi/edgar_concept/derived); kind-specific config required (transcript_kpi requires pattern_hints; edgar_concept requires concept_name; derived requires formula); rejects malformed registry (missing required fields, mismatched kind/config). |

**Phase 2 (HR-Payroll yaml round-trip, depends on Phase 2 data files landing)**:
| Test file | Coverage |
|---|---|
| `AI-excel-addin/tests/fixtures/test_operating_comps_hr_payroll_yaml.py` (new) | Round-trip parse: `config/industry_kpis/hr_payroll.yaml` loads cleanly into `KPIRegistry`; `config/comps_templates/operating_comps_hr_payroll_v1.yaml` loads cleanly into `CompsTemplateManifest`; manifest's `kind: kpi` bindings reference `kpi_key`s present in the registry (cross-file integrity). |
| `AI-excel-addin/tests/fixtures/test_operating_comps_hr_payroll_fixture.py` (new) | Manifest + KPI registry + fixture CSV parity (Track 0 §7.7 pattern): every metric in manifest has matching column in fixture CSV; every KPI referenced via `kind: kpi` exists in registry; fixture row counts align with `years_back`/`years`. |

This split keeps Phase 1 CI green without depending on Phase 2 data artifacts; Phase 2's CI gate adds the cross-file parity tests once the yaml/CSV files land.

~40-60 test cases across 10 new files (6 risk_module + 4 AI-excel-addin). Existing Track A tests must continue to pass (operating_comparison addition is additive at top level).

---

## 6. Cross-cutting concerns

### 6.1 Sources from EDGAR + transcripts
Producer constructs `SourceRecord` from `DispatchResult.source_meta` (per TB.D4) using these shapes (Track 0 R4 enum):
- **EDGAR concept fetch** → `source_meta = {accession, form, fiscal_year, concept, retrieved_at, raw_payload}` becomes:
  - `type: "filing"`, `source_id: source_meta["accession"]`, `endpoint_or_filing_id: f"{form}_{fiscal_year}_{concept}"`, `key_fields: {symbol, form, fy: fiscal_year, concept}`, `text: ""`, `provider: "edgar"`, `retrieved_at: source_meta["retrieved_at"]`
  - When `accession is None` (parser couldn't resolve), fall back to `source_id=f"edgar:{ticker}:{fiscal_year}:{concept}"` so SourceRecord IDs remain stable for downstream registry lookups.
- **Transcript KPI fetch** → `source_meta = {quarter, fiscal_year, kpi_key, matched_excerpt, retrieved_at}` becomes:
  - `type: "transcript"`, `source_id: f"fmp_transcripts:{ticker}:{fiscal_year}Q{quarter}"`, `endpoint_or_filing_id: "earning_call_transcript"` (the FMP underlying-endpoint identifier label, not a function-call name — Track B calls the existing `get_earnings_transcript` wrapper per TB.D8), `key_fields: {symbol, fy: fiscal_year, quarter, kpi_key}`, `text: source_meta["matched_excerpt"]`, `provider: "fmp"`, `retrieved_at: source_meta["retrieved_at"]`
- **Annual FMP financial fetch** → no `source_meta` (Track A-style; built from endpoint marker only via `_source_id_for_annual_endpoint` per TB.D5):
  - `type: "other"`, `source_id: f"fmp:{endpoint}:{ticker}:annual:{fiscal_year}"`, `endpoint_or_filing_id: endpoint`, `key_fields: {symbol, period: "annual", fiscal_year}`, `text: ""`, `provider: "fmp"`, `retrieved_at` from per-endpoint timestamp dict

### 6.2 Caching (per TB.D8)
- EDGAR concept cache: 24h TTL per `(ticker, concept, fiscal_year)`
- Transcript KPI cache: 24h TTL per `(ticker, kpi_key, fiscal_year)`
- Both follow Track A's TTLCache pattern with `retrieved_at` preserved on cache hit (so SourceRecord identity is stable)

### 6.3 Error handling
- `kind: edgar_concept` lookup fails / concept missing → cell value `None`, `source_refs: []`; metric still appears in section per `null_policy: "skip"`
- `kind: transcript_kpi` no pattern match → cell value `None`, `source_refs: []`
- KPI registry missing for a known industry_key → operating_comparison omitted; `portfolio_logger.warning` logged (silent-skip per TB.D6 — single MCP tool also serves Track A and must not break for non-HR-Payroll industries in v1)
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

**Schema-first ordering**: any data manifest that uses `kind: "kpi"` or `years` / `years_back` would be REJECTED by the current AI-excel-addin schema (`comps_template.py:11` Literal lacks `"kpi"`; `_ContractModel` is `extra="forbid"` per `thesis_shared_slice.py:66-68`). The schema bumps and the new `KPIRegistry` Pydantic model MUST land before any HR-Payroll yaml fixture is committed. Phases re-ordered accordingly:

1. **Phase 1 (AI-excel-addin schema)**: extend `schema/comps_template.py` per TB.D3 + TB.D4 (`kind` Literal adds `"kpi"`; `CompsTemplateManifest` adds `years` / `years_back` + cross-field validator) and ship `schema/kpi_registry.py` (Pydantic model for industry KPI registries) + Phase 1 schema tests (per §5 — `test_comps_template_operating_comps.py` + `test_kpi_registry.py`, INLINE-FIXTURE only, no yaml dependency). No data manifests yet, no risk_module changes. Lands flag-off.
2. **Phase 2 (AI-excel-addin data)**: ship HR-Payroll yaml registry + operating-comps manifest + fixture CSV + Phase 2 fixture tests (per §5 — `test_operating_comps_hr_payroll_yaml.py` + `test_operating_comps_hr_payroll_fixture.py`, exercising round-trip yaml→Pydantic and manifest/registry/fixture parity). Now schema accepts them. Data + tests commit.
3. **Phase 3 (risk_module helpers — fetchers)**: ship `fmp/tools/edgar_concept_fetcher.py` + `fmp/tools/transcript_kpi_fetcher.py` + `fmp/tools/peer_annual_bundle.py` + their tests. No producer wiring yet.
4. **Phase 4 (risk_module dispatcher)**: extend `manifest_source_dispatcher.py` — `DispatchResult` gains `source_meta` (additive third field); `dispatch_source_binding` gains kw-only `fiscal_year` and `kpi_registry` (both default None — Track A unaffected); three new `kind` branches added (`kpi`, `edgar_concept`, `transcript_kpi`). Backward-compat tests for Track A unpack sites + new dispatcher tests per §5.
5. **Phase 5 (risk_module orchestrator)**: ship `utils/kpi_registry_loader.py` + `utils/timeseries_collector.py` + tests.
6. **Phase 6 (risk_module producer wire-up)**: extend `mcp_tools/industry.py` to emit `operating_comparison` when flag on + industry known + registry exists; add `_source_id_for_annual_endpoint` helper; add EDGAR/transcript SourceRecord branches per §6.1. Integration tests. Flag-off shipping.

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

- **5 new modules** in risk_module (`edgar_concept_fetcher`, `transcript_kpi_fetcher`, `peer_annual_bundle`, `timeseries_collector`, `kpi_registry_loader`)
- **2 modified modules** in risk_module (`fmp/tools/manifest_source_dispatcher.py` — DispatchResult third field, three new `kind` branches, kw-only `fiscal_year` + `kpi_registry`; `mcp_tools/industry.py` — additive `operating_comparison` field + `_source_id_for_annual_endpoint` helper + EDGAR/transcript SourceRecord branches)
- **3 new yaml/csv files** in AI-excel-addin (HR-Payroll registry + manifest + fixture)
- **1 new Pydantic schema** in AI-excel-addin (`kpi_registry.py`)
- **1 modified schema** in AI-excel-addin (`comps_template.py` — `kind: "kpi"` on `CompsManifestSourceBinding`; `years` / `years_back` on `CompsTemplateManifest` + cross-field validator)
- **10 new test files** (~40-60 cases — 6 risk_module + 4 AI-excel-addin per §5)
- **0 new patch ops** (Track 0 shipped them; persistence-to-Thesis OOS)
- **0 schema changes to thesis_shared_slice** (Track 0 already shipped `OperatingComparison`/`TimeseriesGroup`/`TimeseriesMetric`)

After Track B merges (flag-off), the canonical comps framework is **complete for v1**. Flag-on integration is a separate downstream gate (renderer + skill consumers ready). v1.1 adds Grocers + a third reference industry as data-only commits.

---

## 11. Changelog

### R0 → R1 (2026-05-07)

Addresses Codex R0 review FAIL (5 P1 + 4 P2). All findings cite shipped Track 0/A code; verified by file read at R1 start (no parallel-session drift).

**P1-1 — Dispatcher contract grounded** (TB.D4, §2 audit, §4): R0 said dispatcher returns `DispatchResult(value, source_record)`. Actual: `DispatchResult(value, source_endpoint: str | None)` (`manifest_source_dispatcher.py:11-13`). SourceRecord construction lives at producer level (`mcp_tools/industry.py:168`), not in dispatcher. R1: Track B's three new branches return `(value, endpoint_marker)`; producer constructs SourceRecord with `type="filing"` / `"transcript"` / `"other"` per kind.

**P1-2 — Manifest schema extension required** (TB.D3, §2 audit, §4 AI-excel-addin): R0 implied manifest could already specify year range. Actual: `CompsTemplateManifest` (`comps_template.py:50`) has no `years` / `years_back`, and `_ContractModel` is `extra="forbid"` (`thesis_shared_slice.py:66-68`). R1: schema extends additively with `years: list[int] | None` + `years_back: int | None`; model validator requires exactly one when `template_kind == "operating_comps"`; industry_comps untouched.

**P1-3 — Schema/dispatcher symmetry** (TB.D4, §2 audit): R0 said all three new kinds need schema additions. Actual: Track 0 anticipated the comps work — `kind` Literal at `comps_template.py:11` ALREADY allows `edgar_concept` + `transcript_kpi` (and `kpi_key: str | None` carrier already exists at `comps_template.py:15`). Only `"kpi"` is missing from the Literal. Dispatcher still gets 3 new branches; schema change shrinks to a one-token additive Literal extension.

**P1-4 — Per-year orchestration grounded** (TB.D5, §2 audit, §4): R0 under-specified the per-year fetch path. Dispatcher operates on a TTM bundle (Track A's `_peer_metric_snapshot_cache` populates once per peer for the as-of moment), and the signature has no `fiscal_year` param (`manifest_source_dispatcher.py:58-66`). R1: dispatcher signature gets additive `fiscal_year: int | None = None`; `timeseries_collector` builds a SEPARATE annual bundle per (peer, year) — period="annual" endpoints, not TTM — and passes `fiscal_year=year` through. Per-year derived KPI ordering uses the existing `resolved_metrics`/`resolving` cycle-detection (`manifest_source_dispatcher.py:84-97`); fresh dicts per year. No cross-year derivation in v1.

**P1-5 — Single-MCP-tool fail-loud breaks Track A** (TB.D6): R0 said producer should fail-loud when industry is known but no KPI registry. But the same `industry_peer_comparison()` MCP tool serves Track A AND Track B output, so any non-HR-Payroll known industry would break Track A's snapshot. R1: silent-skip (omit `operating_comparison` field, log warning) — same behavior as `industry_key="unknown"`. Reserve fail-loud for an explicit operating-comps-required entry point (which v1 doesn't expose).

**P2-1 — EDGAR API grounded** (TB.D8, §4): R0 hand-waved a "us-gaap concept by fiscal year" API. Actual: `edgar_parser.tools.get_metric(ticker, year, quarter, metric_name, full_year_mode=False, source="auto", date_type=None) -> dict` at `/Users/henrychien/Documents/Jupyter/edgar-parser/edgar_parser/tools.py:722`. R1: wrapper passes concept name as `metric_name`, uses `quarter=None` + `full_year_mode=True` for annual; extracts first match's `current_value` and accession from `source` metadata (exact field path verified at impl start).

**P2-2 — Existing transcript wrapper used** (TB.D8, §4): R0 said wrapper would call `fmp.fetch_raw("earning_call_transcript", ...)`. Use existing `fmp.tools.transcripts.get_earnings_transcript(symbol, year, quarter, format="full")` at `fmp/tools/transcripts.py:1032` — already has its own per-(symbol, year, quarter) JSON cache. R1: wrapper iterates Q1–Q4 for the fiscal year; module-level cache at the (ticker, kpi_key, fiscal_year) grain avoids re-running pattern matching on cache hit.

**P2-3 — Derived KPI ordering documented** (TB.D5): R0 left dependency ordering implicit. R1: collector iterates metrics in manifest order per year; existing dispatcher `resolved_metrics`/`resolving` mechanism handles single-pass cycle detection within a year. Per-year independence — no cross-year derivation in v1 (e.g., 2y CAGR is computed at presentation time from per-year cells).

**P2-4 — AI-excel-addin schema/fixture tests added** (§5): R0 missed schema-side test coverage. R1: three new test files in AI-excel-addin (`test_comps_template_operating_comps.py`, `test_kpi_registry.py`, `test_operating_comps_hr_payroll_fixture.py`) cover years/years_back validation, kpi-kind acceptance, KPI registry load + validation, manifest/registry/fixture parity. Test count up from ~30-40 to ~40-55.

**P3 — Path prefix cleanup** (throughout): R0 used `risk_module/utils/...` and `risk_module/fmp/tools/...` prefixes; actual repo paths are root-relative. Fixed all 12 occurrences.

### R1 → R2 (2026-05-07)

Addresses Codex R1 review FAIL (3 blockers). Findings cite shipped code; fixes verified against `manifest_source_dispatcher.py:11`, `mcp_tools/industry.py:337-346`, and `comps_template.py:10` + `thesis_shared_slice.py:66`.

**B1 — Source metadata pipeline (TB.D4, §4 dispatcher modification, §6.1)**: R1's `DispatchResult(value, source_endpoint)` discarded EDGAR accession, transcript quarter, matched excerpt, and `retrieved_at` before the producer could build §6.1 SourceRecords. R2: extend `DispatchResult` to `(value, source_endpoint, source_meta: dict | None)` (additive third NamedTuple field, backward-compat for Track A unpack sites that use index access). Track A branches return `source_meta=None` → existing TTM SourceRecord template at `mcp_tools/industry.py:337-346` is unchanged. Track B branches populate `source_meta` with kind-specific keys; producer's §6.1 SourceRecord construction reads from `source_meta` instead of round-tripping fetcher state.

**B2 — Annual FMP bundle helper (TB.D5, §4 risk_module new file)**: R1 said the collector "builds an annual bundle per (peer, year)" but did not specify a helper contract; Track A's TTM path at `industry.py:337-346` hardcodes `period: "ttm"` in `source_id` and `key_fields`, so reuse would corrupt provenance. R2: new file `fmp/tools/peer_annual_bundle.py` with `fetch_peer_annual_bundle(ticker, fiscal_year) -> (bundle, retrieved_at_by_endpoint)`; module-level cache at (ticker, fy) grain (24h TTL). New producer-side helper `_source_id_for_annual_endpoint(...)` parallel to existing `_source_id_for_endpoint`; same shape but with `:annual:{fy}` source_id and `period="annual", fiscal_year=fy` key_fields. Phase 6 wires both.

**B3 — Rollout order schema-first (§8)**: R1's Phase 2 shipped HR-Payroll yaml before any §4 schema bump landed; the AI-excel-addin schema would reject `kind: "kpi"` (Literal lacks the value at `comps_template.py:11`) and `years`/`years_back` (`extra="forbid"` in `_ContractModel` at `thesis_shared_slice.py:66`) on parse. R2: re-ordered to schema-first — Phase 1 ships AI-excel-addin schema bump + `kpi_registry.py` Pydantic + schema tests; Phase 2 ships HR-Payroll yaml/CSV (now valid against the bumped schema); Phases 3-6 are risk_module work as before.

**Confirmed (no change needed)**:
- Dispatcher caller grep: only `mcp_tools/industry.py` and tests call `dispatch_source_binding` — `fiscal_year` defaulted-keyword extension is safe.
- Silent-skip behavior on missing-registry-for-known-industry is coherent with parent framework's "omit silently unless explicitly requested" language.

### R2 → R3 (2026-05-07)

Addresses Codex R2 review FAIL (2 P1). Both findings cite shipped code; fixes verified against `manifest_source_dispatcher.py` signature + `comps_template.py:10` source-binding schema.

**P1.1 — KPI registry data path (TB.D4, TB.D5, §4 dispatcher modification)**: R2's dispatcher branches called `transcript_kpi_fetcher.fetch_kpi_from_transcripts(..., kpi_definition, ...)` and the `kind: kpi` indirection looked up a KPI definition, but the dispatcher had no access to a KPI registry — the source-binding schema only carries `kpi_key: str | None`, and `dispatch_source_binding` never received the registry. R3: add kw-only `kpi_registry: KPIRegistry | None = None` param to `dispatch_source_binding`. Collector loads the registry once (it's already loaded by the producer for the silent-skip decision per TB.D6) and threads it through every per-(metric, year) dispatch call. `kind: kpi` resolves `kpi_key` via the registry then RECURSES into the resolved sub-kind (`edgar_concept` or `transcript_kpi`); `kind: transcript_kpi` reads `kpi_definition.extraction.pattern_hints` from the registry. Track A unaffected (None default; `fmp_endpoint`/`derived` branches don't read it).

**P1.2 — Schema-test phasing (§5, §8)**: R2's §5 included a round-trip test of `hr_payroll.yaml` in Phase 1's schema test list, but Phase 1 ships only the schema (no yaml); Phase 2 ships the data. The test would fail in Phase 1 CI. R3: split the AI-excel-addin tests into Phase 1 (inline-fixture-only schema validation in `test_comps_template_operating_comps.py` + `test_kpi_registry.py`) and Phase 2 (HR-Payroll yaml round-trip + fixture parity in `test_operating_comps_hr_payroll_yaml.py` + `test_operating_comps_hr_payroll_fixture.py`). Phase 1 CI green; Phase 2 CI gate adds cross-file parity once data artifacts land.

**Spot-check confirmations from Codex R2**:
- `source_meta` shape per kind is sufficient to construct §6.1 SourceRecords without re-querying the fetcher.
- `peer_annual_bundle` enables `kind: fmp_endpoint` to work for annual data when the helper prefilters to one annual row per endpoint (collector path doc'd in TB.D5).
- Schema-first ordering (§8 Phase 1 → Phase 2) is directionally right.

### R3 → R4 (2026-05-07)

Addresses Codex R3 review FAIL (2 P1). Both findings cite shipped code; fixes verified against Track A's `resolved_metrics_by_ticker` pattern at `mcp_tools/industry.py:142-166` and `dispatch_source_binding` derived-formula contract at `manifest_source_dispatcher.py:84-97`.

**P1.1 — `kind: kpi` recursion deterministic + EDGAR concept supplied (TB.D2, TB.D4)**: R3's TB.D2 yaml example showed `extraction.sources: [transcript, ir_release, mdna]` (an ordered list), but TB.D4 dispatcher said it constructs ONE synthetic binding from that list — leaving fallback semantics ambiguous and missing the EDGAR concept name supply (registry shape only had `pattern_hints`). R4: each KPI has **exactly one** `extraction.kind` (Literal: `transcript_kpi | edgar_concept | derived`) plus kind-specific config (`pattern_hints`, `concept_name`, or `formula`). v1 = no fallback list; v1.1 may extend to a list with explicit ordering as an additive change. The `kind: kpi` branch reads `kpi_def.extraction.kind` and constructs a synthetic binding of that exact kind, then recurses through `dispatch_source_binding` passing the SAME `fiscal_year` and `kpi_registry` (one-level indirection, bounded — registry KPIs cannot have `extraction.kind == "kpi"`). EDGAR concept name comes from `extraction.concept_name`. Updates: TB.D2 yaml example + Pydantic Literal, TB.D4 branch descriptions.

**P1.2 — Shared `resolved_metrics` per (ticker, fiscal_year) (TB.D5)**: R3's collector said `resolved_metrics={}` fresh per dispatch call, but Track A maintains `resolved_metrics_by_ticker` shared ACROSS the metric loop (`mcp_tools/industry.py:142-144` init, `:166` accumulation) — without that, `kind: derived` formulas like `revenue_per_client = revenue / clients` cannot resolve. R4: collector keeps `resolved_metrics_by_ticker_by_year: dict[str, dict[int, dict[str, Any]]]`. For each (ticker, year), a shared inner dict accumulates across the per-year metric loop and is passed to every dispatch call within that (ticker, year). `resolving=set()` stays fresh per dispatch (matches Track A). Cross-year independence preserved (no writes between years). Updates: TB.D5 collector orchestration with explicit pseudocode.

### R4 → R5 (2026-05-07)

Addresses Codex R4 review FAIL (1 P1 + 1 P2). Both consistency bugs — TB.D5 was correct in R4, but §4 / §5 entries had stale text from earlier rounds.

**P1 — §4 collector entry contradicted TB.D5 (§4)**: §4's `utils/timeseries_collector.py` line at `:317` still said "calls dispatcher per metric per year with fresh `resolved_metrics={}`/`resolving=set()`" — exactly the R3 bug TB.D5 fixed. An implementer who read §4 instead of TB.D5 would reintroduce it. R5: §4 collector entry now states `resolved_metrics_by_ticker_by_year[peer][year]` is shared across the metric loop (analog of Track A's `:142-144` init, `:166` accumulation); only `resolving=set()` is fresh per dispatch.

**P2 — Dispatcher tests claimed SourceRecord construction (§5)**: §5 said `tests/fmp/test_manifest_source_dispatcher_kpi_kinds.py` covers "SourceRecord construction (type=filing/transcript/other)" but per §4 + §6.1, SourceRecord construction is producer-level; the dispatcher only emits `source_endpoint` + `source_meta`. R5: dispatcher tests now assert `DispatchResult.value` + `source_endpoint` marker + `source_meta` dict shape per kind + recursion termination + error handling. Producer-level SourceRecord construction is covered by the existing `tests/mcp_tools/test_industry_v1_2_operating_comps.py` integration test.

### R5 → R6 (2026-05-07)

Doc-consistency cleanup. Three stale references caught by Codex R5 review.

**C1 — §2 gap summary (line 60)**: said "Track B has zero schema work (Track 0 shipped it)" — true for `thesis_shared_slice`, but R1+ added AI-excel-addin schema work (one-token `kind: "kpi"` Literal extension; additive `years`/`years_back` on `CompsTemplateManifest`; new `KPIRegistry` Pydantic). R6: clarifies "zero `thesis_shared_slice` schema work; AI-excel-addin manifest/KPI schema extensions remain."

**C2 — `load_kpi_registry` return type (§4)**: declared as `-> KPIRegistry` while the description said it returns `None` for missing registries. Producer's silent-skip path (TB.D6) depends on the optional return. R6: signature now `-> KPIRegistry | None`.

**C3 — §10 summary mismatches**: counted modified dispatcher as a "new module" and quoted "6 new test files / 30-40 cases" while §5 already lists 10 test files / ~40-60 cases (after R3's Phase 1/2 split). R6: now "5 new modules + 2 modified modules in risk_module"; "10 new test files (~40-60 cases — 6 risk_module + 4 AI-excel-addin)".

### R6 → R7 (2026-05-07)

Two doc-consistency cleanups from Codex R6 review.

**C1 — §2 gap summary repo-attribution**: R6 fixed "zero schema work" → "zero `thesis_shared_slice` schema work" but the same paragraph still attributed "per-industry KPI definitions" and "per-industry manifest content" to risk_module — those actually live in AI-excel-addin (`config/industry_kpis/*.yaml` + `config/comps_templates/operating_comps_*_v1.yaml`). R7: paragraph now splits the gap into two sub-bullets — AI-excel-addin (schemas + yaml/CSV data) vs. risk_module (dispatcher kinds + collector + producer wire-up).

**C2 — Phase 4 missed `kpi_registry` (§8)**: rollout summary said `dispatch_source_binding` gains `fiscal_year` but omitted `kpi_registry`; both §4 file-changes list and §10 summary already include it. R7: Phase 4 entry now lists both kw-only params (`fiscal_year` + `kpi_registry`, both default None — Track A unaffected) plus the three new `kind` branches by name.

---
