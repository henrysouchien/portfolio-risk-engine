# Canonical Comps Framework — High-Level Design

**Status**: DRAFT R6 — minor amendment per Track 0 R3 review finding.
**Created**: 2026-05-07 (R0); revised 2026-05-07 (R1, R2, R3, R4, R5, R6).
**Revision history**:
- R6 — minor amendment surfaced by Track 0 R3 review: §4 Track A shape sketch now uses `template_manifest_id: "industry_comps_generic_v1"` (matches D9). Track A always renders the generic template per D9 ("FMP gap-fill metrics are universal"); the per-industry-key naming was only ever for Track B's operating-comps (`operating_comps_<industry>_v1`). One-line wording fix; functional contract unchanged.
- R5 — addresses Codex R4 FAIL: aligned identity-hash contract between Track 0 (§3.5) and §7.6. R4 had two inconsistent versions: Track 0 said `hash({provider, endpoint_or_filing_id, key_fields})` while §7.6 said `hash({type, source_id, endpoint_or_filing_id, key_fields})`. R5 picks **§7.6's version as canonical** — preserves master-plan `type` + `source_id` in identity, keeps `provider` provenance-only — and updates Track 0 §3.5 to match [P2].
- R4 — addresses Codex R3 FAIL: corrected §7.6 source-registry mapping. `type` is a closed canonical enum (`filing | transcript | investor_deck | other`) per master plan; R3 incorrectly mapped `provider → type` with examples like `"fmp"` / `"edgar"` (changed enum semantics). R4 keeps `type` canonical (FMP endpoint snapshots → `"other"`, EDGAR filings → `"filing"`, transcripts → `"transcript"`) and treats `provider` as a **separate additive** provenance field, not a remap of `type` [P2].
- R3 — addresses Codex R2 PASS-with-2-should-fix: (1) tightened dual-write policy to require **semantic parity** with today's `mcp_tools/industry.py` output (legacy `peers[].key_metrics` and placeholder fields preserved during transition) [P2]; (2) clarified §7.6 registry-entry fields are **additive extensions** to the master plan's canonical `Thesis.sources[]` shape — but R3's `provider → type` mapping was wrong (caught in R4) [P2].
- R2 — addresses Codex R1 FAIL: (1) v1.2 schema bump made **strictly additive** — `peer_comparison.peers` (legacy flat list) preserved; new `sections` added alongside; producers dual-write during transition; deprecation of `.peers` deferred to a future major bump [P1]; (2) SourceRef cells now reference `Thesis.sources[].id` (registry stable ID) NOT provider strings; §7.6 dedupe hash drops `retrieved_at` from identity (logical-identity-only); `retrieved_at` is a separate provenance field on registry entries [P1]; (3) editorial peer-set semantics pinned to existing `compare_peers` convention — `editorial_peer_set` excludes focal ticker (focal is implicit from Thesis); explicit rule documented in §6 [P2]; (4) industry-key taxonomy supports `unknown` as a valid fallback value — Track A renders generic manifest for unknown; Track B fails-loud when requested without known industry_key [P2]; (5) template manifest drift test replaced — committed CSV fixture is the offline canonical reference; live gsheets parity check is optional non-blocking CI job [P2].
- R1 — addresses Codex R0 FAIL: (1) split editorial peer storage from generated artifact via new `industry_analysis.editorial_peer_set` field [P1]; (2) added Track 0 prerequisite for schema/patch ops/versioning, HandoffArtifact v1.1 → v1.2 [P1]; (3) restructured all artifact sketches with cell-level citation shape `values: {ticker: {value, source_refs}}` [P1]; (4) reordered dependency to **Track 0 → C → A → B** [P1]; (5) added code-owned template manifest at `config/comps_templates/` as drift-detected spec [P2]; (6) clarified Track A is FMP-only (EDGAR is Track B's domain) [P2]; (7) moved industry-key taxonomy into Track 0 [P2]; (8) defined source-registry integration via §7.6 [P2]; (9) removed `peer_universe` from v1 KPI registry [P2]; (10) treated process-template migration as gated phased rollout, not mechanical [P2]; (11) dropped `relative_position` from sectioned artifact [P3]; (12) named cache-freshness risks (restatements, manual refresh, filing date) [P3].

**Authoritative design references**:
- `docs/planning/completed/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.2 (`industry_analysis` shared-slice on `HandoffArtifact v1.1`), §6.6 (Thesis shared-slice), §10b.1 (industry-research sourcing — answered "skill, not tool" for narrative parts; this doc covers structured comps).
- `docs/planning/completed/INDUSTRY_RESEARCH_TOOLS_PLAN.md` (Plan #7, SHIPPED 2026-04-28) — tools-only ancestor; populated `peer_comparison.peers[].key_metrics` from FMP. This plan generalizes beyond it.
- Editorial templates of record (Google Drive):
  - `SIA-strategic-industry-comps-SheetsFinance` — single-snapshot industry comps template
  - `SIA-strategic-operating-comps-SheetsFinance` — multi-year operating comps template
  - `-Grocers` populated examples for both

---

## 1. Purpose

Formalize the editorial **canonical comps** templates already in use (`SIA-strategic-industry-comps`, `SIA-strategic-operating-comps`) as code-side artifacts that:

1. Populate `industry_analysis.peer_comparison` (snapshot) and a new `industry_analysis.operating_comparison` sibling (multi-year + KPIs) with template-shaped, citable data
2. Read from a separate `industry_analysis.editorial_peer_set` field for editorial peer overrides (input ≠ output)
3. Integrate with the SIA-course **knowledge wiki** + **methodology** layers via downstream industry-analysis skills (skill work itself is a separate track)
4. Replace today's `industry_peer_comparison` thin reshape with a richer, gap-filled artifact aligned to the editorial templates

The editorial templates are **the spec**, snapshotted into a code-owned **template manifest** at `config/comps_templates/`. FMP / EDGAR / SF formulas are the data sources that feed the manifest's metric definitions. Code-side artifacts remain template-shaped, not "tool output + extras."

---

## 2. Audit findings

| Surface | State | Notes |
|---|---|---|
| `compare_peers` (`fmp/tools/peers.py`) | 22 financial metrics, single snapshot, FX-aware, TTL-cached | Auto-discovers peers via `get_subindustry_peers_from_ticker` → FMP `stock_peers` fallback. Has `format="full"` and `format="summary"`; only summary surfaced via MCP |
| `industry_peer_comparison` (`mcp_tools/industry.py`) | Thin reshape over `compare_peers` | Populates only `peer_comparison.peers[].key_metrics`. `relative_position: None`, `name=ticker`, `source_refs: []` are placeholders. Plan #7 v1 limitations |
| `industry_analysis` schema (`AI-excel-addin/schema/thesis_shared_slice.py`) | 4 sub-fields shipped | `landscape`, `peer_comparison`, `macro_overlay`, `structural_trends`. Renderer wired (`HandoffSectionRenderer.tsx:420`) |
| Process templates (`AI-excel-addin/config/process_templates/*.yaml`) | 4 templates require `peers` section | None require `industry_analysis` — schema/template drift |
| EDGAR parser KPI extraction | In progress | Generic concept extraction exists; no per-industry KPI definition layer |
| Per-industry KPI registry | **Does not exist** | Operational KPIs (Clients, Retention, Rev/client, etc.) have no code-side definition |
| Editorial peer set storage | **Does not exist** | Auto-discovery only; no override mechanism for editorial peer lists |
| SIA knowledge wiki | Markdown `MethodologyUnit` files in AI-excel-addin | Industry-structure / competitive-advantage articles flagged as Phase 4 future per `KNOWLEDGE_LAYER_WIKI_DESIGN.md` |
| SheetsFinance MCP | Catalog of 31 SF() formulas; building-block layer | Used to construct gsheet templates by hand |

**Gap summary:** the editorial templates are richer than current code outputs along three axes simultaneously (more metrics, multi-year time-series, operational KPIs), and the editorial peer set has no storage path. Skills layer (downstream) can't reliably consume comps because the artifact shape doesn't match the template.

---

## 3. Locked design decisions

These decisions frame the four tracks (Track 0 prerequisite + Tracks A/B/C). Implementation plans inherit them.

### D1. Templates are the spec; template manifest is code-owned
The editorial templates (`SIA-strategic-industry-comps`, `SIA-strategic-operating-comps`) define the artifact shape. A code-owned **template manifest** (yaml at `config/comps_templates/<template_id>.yaml`) snapshots the manifest's structure: section names, metric keys, ordering, units, formulas, null policy, aggregation rules. Editorial Google Sheets remain the human-editable reference; the manifest is the code spec. A parity test detects drift (see §7.7).

### D2. Artifact shape mirrors the template manifest
Industry comps and operating comps each ship as a typed nested dict that preserves the manifest's named subgroups (e.g., `Performance (LTM)`, `Valuation`, `EPS forward`, `Dividend`). The renderer arranges by section; skills cite by section + metric.

### D3. Operating comps gets its own sibling field
`industry_analysis.peer_comparison` (snapshot, mostly financial — Track A) and `industry_analysis.operating_comparison` (multi-year time-series, mixed financial + operational — Track B) are conceptually distinct shapes; forcing them under one field would compromise both.

### D4. Per-industry KPI registry is yaml-first; definitions only
Lives at `config/industry_kpis/<industry_key>.yaml`. Yaml matches the existing process-template pattern, is easy to edit by hand, and can be promoted to DB later if user overrides become first-class. **The registry holds KPI definitions only — no `peer_universe`** (peers come from `editorial_peer_set` or auto-discovery; per D5).

### D5. Editorial peer set: separate field, per-thesis only for v1
Editorial peer overrides live in **`Thesis.industry_analysis.editorial_peer_set`** — a new field shipped in Track 0, **structurally separate from `peer_comparison.peers`** (the generated artifact). This eliminates the input-vs-output collision. Override rule: if `editorial_peer_set` is non-empty, downstream tools use it as the peer universe verbatim; otherwise fall back to FMP auto-discovery via `get_subindustry_peers_from_ticker`. Per-industry peer registry is deferred to v2.

### D6. Citation model: cell-level source_refs via embedded value objects
Every metric cell carries citations via the shape:
```yaml
values:
  <ticker>:
    value: <scalar>
    source_refs: [<thesis_source_id>, ...]   # registry IDs, NOT provider strings
```
For time-series: `series: {<ticker>: {<year>: {value, source_refs}}}`. Mixed-source rows (e.g., LTM revenue from FMP + retention from a transcript) are first-class. Computed cells (medians, derived ratios) carry empty `source_refs` with `derived: true`. **`source_refs` always reference the stable registry `id` of an entry in `Thesis.sources[]` — never provider-side identifiers (per §7.6 contract).**

### D7. Update cadence: pull-on-demand with TTL cache; freshness risks named
- Track A: 15-min TTL per-ticker snapshot (matches existing `compare_peers` cache)
- Track B: 24-hour TTL per peer-year-KPI tuple
- Cache invalidation: explicit refresh tool for both, no auto-invalidate on filing
- **Freshness risks named** (resolution deferred to per-track impl plans): restatements (10-K/A revisions invalidate prior cells), filing-date staleness (no auto-refresh), manual refresh semantics for Thesis snapshots (frozen-at-snapshot vs live-on-read), source-version pinning for reproducible scorecards.

### D8. Schema versioning: HandoffArtifact v1.1 → v1.2 (strictly additive)
v1.2 is a **minor bump that adds fields only** — no shape changes to existing fields. Per master plan §8, minor bumps must be additive; breaking changes require a major bump.

**Additive changes only:**
- New field: `industry_analysis.editorial_peer_set`
- New field: `industry_analysis.operating_comparison`
- New field: `industry_analysis.peer_comparison.sections` (added alongside existing `peers`)
- New field: `industry_analysis.peer_comparison.industry_key`
- New field: `industry_analysis.peer_comparison.template_manifest_id`
- New field: `industry_analysis.peer_comparison.as_of`

**Preserved unchanged:**
- `industry_analysis.peer_comparison.peers` (legacy flat list — stays exactly as v1.1)

**Producer transition policy**: Track A producers **dual-write** during transition — populate both `peers` (legacy, for existing readers) and `sections` (new, sectioned with cell-level citation). New readers consume `sections`; existing readers continue reading `peers` unchanged.

**Dual-write semantic parity** (closes R2 [P2]): the legacy `peers` entries written during transition must have **the same shape and semantics as today's `mcp_tools/industry.py` output** — i.e., `{ticker, name, key_metrics, relative_position, source_refs}` per `mcp_tools/industry.py:48-57`. Track A producers populate `key_metrics` from the same `compare_peers` summary used today (subset of the new `sections` data), keep `relative_position: None`, `name=ticker` placeholders to preserve byte-equivalence, and use the registry IDs in `source_refs`. The richer cell-level-cited data lives only in `sections`. Existing readers see no regression.

**Future deprecation**: removing `peers` in favor of `sections` would be a major bump (v2.0); explicitly out of scope for this plan.

Thesis shared-slice changes are also strictly additive (lockstep with Handoff per the unification plan's lockstep rule). v1.2 writes are gated by feature flag (`INDUSTRY_ANALYSIS_V1_2_ENABLED`) during rollout.

### D9. Industry-key taxonomy with `unknown` fallback
`industry_key` is required by Track A (artifact field) and Track B (KPI registry key). Taxonomy decision (GICS sub-industry / FMP industry / custom editorial mapping) lives in Track 0. Initial v1 mapping enumerates 2-3 reference industries (HR-Payroll, Grocers, +1 TBD) **plus the reserved value `"unknown"`**.

**Unknown-industry fallback semantics:**
- **Track A**: renders `peer_comparison.sections` using a **generic template manifest** (`industry_comps_generic_v1`) — the FMP gap-fill metrics are universal, so artifact ships even without a known industry. Industry-median row is computed across the peer set without industry-wide context.
- **Track B**: requires a known `industry_key` (operating-comps depends on the per-industry KPI registry). For unknown industries, Track B **does not produce `operating_comparison`** — fail-loud when explicitly requested, omit silently otherwise.

This unblocks Track A for any ticker outside the reference industries while keeping Track B scoped to industries with curated KPI registries. New industries added to the taxonomy via per-industry impl plans following the v1 template.

---

## 3.5 Track 0 — Schema & patch ops (prerequisite)

**Goal**: ship the schema/contract changes that Tracks A, B, C all depend on. Without Track 0, the follow-on tracks are building on a nonexistent contract.

**Scope:**
- HandoffArtifact v1.1 → v1.2 schema bump — **strictly additive per D8** (Thesis + Handoff lockstep per unification plan)
- New field: `industry_analysis.editorial_peer_set: list[EditorialPeer]`
  - `EditorialPeer = {ticker, name, source: "editorial", added_by, added_at, rationale?}`
  - **Excludes focal ticker by convention** (focal is implicit from Thesis.ticker; matches existing `compare_peers` semantics)
- New field: `industry_analysis.operating_comparison: OperatingComparison` (shape per §5)
- New field: `industry_analysis.peer_comparison.sections: list[Section]` with cell-level citation per D6 (added alongside existing `peers`; legacy field preserved unchanged)
- New patch ops: `set_editorial_peer_set`, `add_editorial_peer`, `remove_editorial_peer`, `set_peer_comparison_sections` (sets the new sections field), `set_operating_comparison`
- **Producer dual-write policy** (per D8): Track A writers populate both `peers` (legacy) and `sections` (new) during transition; no canonicalizer needed since both shapes coexist on the wire
- Feature flag: `INDUSTRY_ANALYSIS_V1_2_ENABLED` gates v1.2 writes (new fields)
- **Industry-key taxonomy locked**: chosen scheme (GICS sub-industry vs FMP industry vs custom editorial mapping) with v1 enumerated set covering 2-3 reference industries **plus reserved `"unknown"` per D9**
- **Template-manifest schema**: `comps_templates/<template_id>.yaml` schema definition (used by §7.7)
- **Source registry contract** (shared with §7.6 — single canonical identity hash):
  - Cell-level `source_refs` always reference `Thesis.sources[].id` (registry stable ID), never provider strings
  - **Stable ID = deterministic hash of `{type, source_id, endpoint_or_filing_id, key_fields}`** (logical-identity fields only, matching §7.6 exactly)
  - `provider`, `retrieved_at`, and content fields (text/span) are **excluded** from identity — they are provenance metadata
  - Same logical source dedupes across pulls (different `retrieved_at`, same identity hash → same `id`)
  - Helper utilities for ID minting, dedupe, and registration

**Why this is its own track**: Tracks C, A, B all write to fields that don't exist yet. Per the unification plan, schema changes are lockstep across Thesis + Handoff and require explicit versioning. Renderer/process-template alignment is gated after Track 0.

**Out of scope for Track 0**: actual data population (that's A and B), peer-curation skill (downstream), full KPI library (start with reference industries from D9), removal/deprecation of legacy `peer_comparison.peers` (would be major bump v2.0; future).

---

## 4. Track A — Industry comps artifact

**Goal**: ship a template-shaped artifact under `industry_analysis.peer_comparison` matching the `SIA-strategic-industry-comps` template manifest, populated from FMP.

**Data source**: pure FMP. All gaps below are FMP-addressable (additional endpoints or surfacing existing rows already fetched in `_fetch_ratios_and_estimates`). EDGAR is **not** required for industry comps — that's Track B's domain (operating KPIs from filings).

**Shape (sketch — conforms to D6 cell-level citation; final shape lives in impl plan):**
```yaml
peer_comparison:
  # Legacy field preserved (D8 additive rule); Track A producers dual-write both.
  # Shape MUST match today's mcp_tools/industry.py output for semantic parity:
  peers:
    - {ticker, name, key_metrics, relative_position: None, source_refs}
    # ... existing readers see byte-equivalent shape

  # New v1.2 fields (additive per D8)
  industry_key: "hr_payroll"                            # or "unknown" per D9
  template_manifest_id: "industry_comps_generic_v1"     # Track A always uses generic snapshot manifest per D9
  as_of: "2026-05-07"
  sections:
    - name: "Performance (LTM)"
      metrics:
        - key: revenue_ltm
          label: "Revenues ($M)"
          units: usd_millions
          values:
            PCTY: {value: 1500.0, source_refs: ["src_a1b2c3"]}     # registry IDs only
            PAYC: {value: 1700.0, source_refs: ["src_d4e5f6"]}
            # ...
          median: {value: 1600.0, source_refs: [], derived: true}
        - key: ebitda_ltm
          # ...
    - name: "Valuation"
      metrics: [...]
    - name: "EPS forward"
      metrics: [...]              # FY1, FY2, FY3 from FMP analyst_estimates
    - name: "P/E multiples"
      metrics: [...]
    - name: "Estimates (NTM)"
      metrics: [...]
    - name: "Dividend"
      metrics: [...]
```

**Unknown-industry behavior (per D9)**: when the focal ticker has no curated industry mapping, `industry_key: "unknown"` and `template_manifest_id: "industry_comps_generic_v1"`. All FMP gap-fill metrics still ship; the "industry median" row reduces to a peer-set median (no industry-wide context).

**Gaps to close vs current `compare_peers` (all FMP-addressable):**
- Industry-median row (computed across peers, configurable per-metric: median / mean / weighted)
- FY1 / FY2 / FY3 EPS estimates (FMP `analyst_estimates` already fetched in `_fetch_ratios_and_estimates`; not surfaced)
- 2-year EPS CAGR (derived from FY1/FY3)
- ROE (in addition to existing ROIC)
- Absolute Net Debt + Cash (currently only `netDebtToEBITDATTM`)
- Dividends Paid + Dividend per Share (currently only `dividendYieldTTM`)
- D&A, EBIT (currently only EBITDA)

**Peer set**: reads from `Thesis.industry_analysis.editorial_peer_set` if non-empty (Track C). Editorial set excludes focal ticker (per §6 convention); Track A prepends focal to form the comparison universe. If `editorial_peer_set` is empty, falls back to `get_subindustry_peers_from_ticker` → FMP `stock_peers` (which already excludes focal).

**Skill integration**: skills read the artifact, do not re-fetch. Wiki + methodology context (separate track) is layered by the skill at synthesis time.

---

## 5. Track B — Operating comps + per-industry KPI registry

**Goal**: ship a multi-year operating-comps artifact under `industry_analysis.operating_comparison` driven by a per-industry KPI registry. Plugs into existing EDGAR-parser KPI extraction.

**Per-industry KPI registry (yaml — definitions only, no peers per D4/D5):**
```yaml
# config/industry_kpis/hr_payroll.yaml
industry_key: hr_payroll                 # matches Track 0 taxonomy
display_name: HR / Payroll
template_manifest_id: "operating_comps_hr_payroll_v1"
kpis:
  - key: clients
    label: Clients
    units: count
    definition: "Total customers paying for payroll/HCM service"
    aliases: [customers, subscribers, merchants]   # extraction hints
    extraction:
      sources: [transcript, ir_release, mdna]      # not in standardized financials
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
    derived_from:                         # computed from other KPIs
      formula: revenue / clients
  # ... etc
financial_metrics:                        # universal, ordered per template manifest
  - revenue
  - sales_growth
  - sm_expense
  - sm_pct_sales
  # ...
```

**No `peer_universe` in registry v1.** Peers come from `editorial_peer_set` (Track C) or auto-discovery — never from the KPI registry. Per-industry peer registry is v2.

**Artifact shape (sketch — conforms to D6 cell-level citation):**
```yaml
operating_comparison:
  industry_key: "hr_payroll"
  template_manifest_id: "operating_comps_hr_payroll_v1"
  years: [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
  metric_groups:
    - name: "Operational"
      metrics:
        - key: clients
          label: "Clients"
          units: count
          series:
            PCTY:
              2022: {value: 33300, source_refs: ["src_7g8h9i"]}    # registry IDs only
              2023: {value: 36500, source_refs: ["src_j0k1l2"]}
              # ...
            PAYC:
              # ...
          median_series:
            2022: {value: 28000, source_refs: [], derived: true}
            # ...
    - name: "Financial"
      metrics: [...]
```

**Extraction pipeline:**
1. Resolve `industry_key` (Track 0 taxonomy) for the focal ticker
2. **If `industry_key == "unknown"`**: skip operating_comparison entirely (fail-loud only when explicitly requested per D9). Track A still produces `peer_comparison` independently.
3. Load registry → KPI definitions + extraction hints
4. For each peer × KPI, route to source per `extraction.sources`
5. Register source via §7.6 helpers — receive back the registry's stable `id` and use it in `source_refs`
6. Cache per peer-year-KPI tuple (24h TTL)

**Peer set**: same as Track A — reads from `editorial_peer_set` (excludes focal) or falls back to auto-discovery, then prepends focal.

**Out of scope for v1**: cross-industry comparability (e.g., "how does AAPL's gross margin compare to PCTY's?"). Operating comps are intentionally industry-keyed.

---

## 6. Track C — Editorial peer set

**Goal**: storage + override semantics for editorial peer lists; feeds Tracks A and B. Structurally separate from the generated artifact to eliminate input/output collision (per D5).

**Storage**: `Thesis.industry_analysis.editorial_peer_set` — new field shipped in Track 0. **Distinct from `peer_comparison.peers`** (the generated artifact written by Track A).

**Focal-ticker convention** (matches existing `compare_peers` semantics): `editorial_peer_set` contains **peers only — focal is excluded**. The focal ticker is implicit from the Thesis (`Thesis.ticker` or equivalent) and is prepended by Tracks A and B at artifact-build time. If `compare_peers` receives an editorial list that contains the focal, the focal is filtered out (matches `peer_list = [t for t in peer_list if t != symbol]` at `fmp/tools/peers.py:417`).

```yaml
editorial_peer_set:
  # Note: focal ticker (e.g., PCTY if PCTY is the Thesis ticker) is NOT in this list
  - ticker: PAYC
    name: "Paychex / Paycom"     # disambiguated by impl
    source: editorial
    added_by: "henry"
    added_at: "2026-05-07T..."
    rationale: "Direct mid-market HCM competitor"
  - ticker: ADP
    # ...
```

**Override rule**: if `editorial_peer_set` is non-empty, downstream tools use it as the peer universe verbatim (after focal-exclusion enforcement). If absent or empty, fall back to FMP auto-discovery via `get_subindustry_peers_from_ticker`. No silent merging — explicit-wins-or-falls-back.

**Skill interface (downstream — out of scope here)**: a peer-curation skill proposes a peer list (e.g., from FMP discovery + sub-industry classifier + user description), user confirms, skill writes via `set_editorial_peer_set` / `add_editorial_peer` patch ops (Track 0).

**Versioning**: peer-set edits are audited via the Thesis CAS model already in place. Historical peer sets are recoverable from Thesis snapshots.

---

## 7. Cross-cutting concerns

### 7.1 Citation model
Cell-level via D6. All artifact sketches in §4 and §5 conform.

### 7.2 Caching + freshness risks
- Track A: 15-min TTL per-ticker snapshot (matches existing `compare_peers` cache)
- Track B: 24-hour TTL per peer-year-KPI tuple
- Cache invalidation: explicit refresh tool for both, no auto-invalidate on filing
- **Freshness risks named** (resolution deferred to per-track impl plans): 10-K/A restatements invalidate prior cells; filing-date staleness has no auto-refresh; manual refresh semantics for Thesis snapshots (frozen-at-snapshot vs live-on-read) need decision; source-version pinning is required for reproducible scorecards.

### 7.3 SIA wiki + methodology integration (downstream)
Skills consume:
- The comps artifacts (Tracks A + B) as structured data
- SIA wiki industry-structure / competitive-advantage articles for narrative context
- Methodology units for analytical framework (5-pillar quality, etc.)

This plan does not design the skills themselves. It only ensures the artifacts are skill-ready: typed, cited, template-shaped.

### 7.4 Process template alignment (gated migration, not mechanical)
Existing process templates (`compounder.yaml`, etc.) require `peers` section. Migrating to require `industry_analysis` is **not mechanical**: existing workflows, validators, and completion gates expect `peers`. Phased migration:
1. **Phase 1**: keep `peers` requirement; add optional `industry_analysis` rendering when present (no required-section change)
2. **Phase 2**: stage by template (compounder first as reference); new templates require `industry_analysis`, existing templates dual-required
3. **Phase 3**: deprecate `peers` requirement after all templates and consumer skills updated

Treat as its own gated rollout, not a single line-item commit. Sequencing decided once Track A ships.

### 7.5 Renderer
Existing `HandoffSectionRenderer.tsx` industry_analysis dispatch handles the current flat `peer_comparison.peers` list. The sectioned `peer_comparison` shape (Track 0) needs a renderer update (new branch); `operating_comparison` is a new render branch (multi-year tabular). Renderer impl belongs to Track A's and Track B's follow-on plans respectively.

### 7.6 Source registry integration
SourceRefs (FMP endpoint snapshots, EDGAR filing + section, transcript spans) must be registered in `Thesis.sources[]` per the unification plan's citation contract. Cell-level `source_refs` always reference the registry's stable `id` — never provider-side identifiers.

**Logical-identity stable ID**: each registry entry has a deterministic `id` computed from **logical-identity fields only**: `{type, source_id, endpoint_or_filing_id, key_fields}`. This means:
- The same logical source pulled at different times resolves to the same `id` → dedupes correctly across pulls
- `retrieved_at` is **NOT** part of identity (it's provenance metadata on the registry entry, not the dedupe key)

**Field naming — additive extension to master plan's canonical shape, not a parallel registry**:
- **Canonical fields preserved unchanged** per master plan §6.6 `Thesis.sources[]`: `id`, `type` (closed enum: `filing | transcript | investor_deck | other`), `source_id`, `section/text/span` (and other shape-specific fields). These remain the contract; this plan does **not** redefine or extend the `type` enum.
- **Comp-data sources map onto canonical types**:
  - **EDGAR filings** → `type: "filing"` (canonical)
  - **Earnings transcripts** → `type: "transcript"` (canonical)
  - **FMP endpoint snapshots** → `type: "other"` (canonical) — FMP is neither a filing nor a transcript
  - **Investor decks** → `type: "investor_deck"` (canonical) — for IR-release sources where applicable
- **`source_id`** (canonical): provider-side opaque identifier (e.g., FMP endpoint signature string, EDGAR accession number, transcript provider's span ID).
- **Additive provenance/identity fields** (new — NOT remappings):
  - `provider`: name of the data provider (e.g., `"fmp"`, `"edgar_parser"`, `"fmp_transcripts"`). Lives alongside `type`, doesn't replace it.
  - `endpoint_or_filing_id`: sub-resource identity within a provider (FMP endpoint name like `"ratios_ttm"`, EDGAR filing accession + section)
  - `key_fields`: parameter-level identity (e.g., `{symbol, period}`)
  - `retrieved_at`: provenance only (NOT part of identity hash)
- Track 0 ships these additive fields without disturbing existing entries or the `type` enum.

**Registry entry shape (sketch — additive over master canonical)**:
```yaml
sources:
  # Example 1: FMP endpoint snapshot
  - id: "src_a1b2c3"                           # canonical — used in source_refs
    type: "other"                              # canonical enum (FMP isn't filing/transcript)
    source_id: "fmp:ratios_ttm:PCTY:ttm"       # canonical — provider opaque ID
    provider: "fmp"                            # additive — provider name
    endpoint_or_filing_id: "ratios_ttm"        # additive — sub-resource
    key_fields: {symbol: "PCTY", period: "ttm"} # additive — params
    retrieved_at: "2026-05-07T14:32:00Z"       # provenance only

  # Example 2: EDGAR 10-K section
  - id: "src_d4e5f6"
    type: "filing"                             # canonical
    source_id: "0001640147-23-000123"          # canonical — EDGAR accession
    provider: "edgar_parser"                   # additive
    endpoint_or_filing_id: "10-K_2022_mdna"    # additive — section identity
    key_fields: {symbol: "PCTY", form: "10-K", fy: 2022, section: "mdna"}
    retrieved_at: "2026-05-07T14:34:00Z"
    # ... canonical section/text/span fields per master plan when applicable

  # Example 3: Earnings transcript
  - id: "src_g7h8i9"
    type: "transcript"                         # canonical
    source_id: "fmp_transcripts:PCTY:Q4_2023"  # canonical
    provider: "fmp_transcripts"                # additive
    key_fields: {symbol: "PCTY", quarter: "Q4_2023"}
    retrieved_at: "2026-05-07T14:36:00Z"
    # ... canonical span fields per master plan
```

**Identity hash (logical-identity-only, used to compute `id`)**: hash of `{type, source_id, endpoint_or_filing_id, key_fields}`. `provider`, `retrieved_at`, and content fields (text/span) are excluded from identity.

**Snapshot behavior**: Thesis snapshots freeze the registry `id` set; subsequent comp reads against a snapshot use the same registered IDs. New pulls of the same logical source land at the same `id`, just with updated `retrieved_at`.

Registration helpers live in shared schema utilities (Track 0 deliverable). Per-track impl plans detail provider-specific `key_fields` schemas (FMP endpoint signature, EDGAR section span, transcript char range).

### 7.7 Template manifest as code-owned spec
Each editorial template has a code-owned manifest snapshot at `config/comps_templates/<template_id>.yaml` (manifest schema defined in Track 0):
- Section names + ordering
- Metric keys + display labels + units + null policy
- Aggregation rules per metric (median / mean / weighted)
- Source editorial template's gsheet ID + version metadata

**Drift detection — fixture-first, not gsheets-dependent**:
- Each manifest ships with a committed **CSV fixture** (e.g., `config/comps_templates/<template_id>.fixture.csv`) that is the offline canonical reference exported from the editorial template at manifest creation time
- The deterministic offline parity test compares manifest structure against the committed fixture (no network, no credentials, runs in any CI)
- An optional non-blocking CI job re-exports the live editorial template via `gsheets-mcp` and compares against the manifest + fixture — when credentials are available; warns on drift, does not gate merges
- Editorial template (gsheet) remains the human-editable reference; the manifest is the code contract; the fixture is the deterministic test artifact

This avoids making CI dependent on live Google Sheets access while still surfacing drift when it happens.

---

## 8. Out of scope

- **Skill implementations** — peer-curation, comps-narrative, industry-analysis synthesis skills are downstream. This plan defines the artifact contract they consume.
- **Full KPI library across all industries** — start with 2-3 reference industries (HR-Payroll, Grocers, +1 TBD); extend incrementally.
- **Per-industry editorial peer registry (v2)** — only per-thesis `editorial_peer_set` in v1.
- **Cross-industry comparability** — operating comps are industry-keyed by design.
- **Renderer redesign** — new branches added for sectioned `peer_comparison` and `operating_comparison`; no full redesign.
- **Live-updating comps** — no streaming / pub-sub on comp data; pull-on-demand with TTL only.
- **Wiki article authoring tools** — wiki content compilation lives in `KNOWLEDGE_LAYER_WIKI_DESIGN.md`.
- **Backfill of historical Thesis snapshots to v1.2 schema** — readers handle v1.1 via canonicalizer; writers move forward; no retroactive backfill.

---

## 9. Follow-on implementation plans

Each track gets its own full impl plan with Codex review:

1. **`SCHEMA_AND_PATCH_OPS_PLAN.md` (Track 0 — prerequisite)**
2. `EDITORIAL_PEER_SET_PLAN.md` (Track C)
3. `INDUSTRY_COMPS_ARTIFACT_PLAN.md` (Track A)
4. `OPERATING_COMPS_KPI_REGISTRY_PLAN.md` (Track B)

**Ordering**: **Track 0 → C → A → B**. Track 0 is hard prerequisite (the new fields don't exist without it). C is smallest and unblocks A's and B's peer-set inputs. A is a gap-fill on shipped FMP tooling. B is the most architecturally novel (KPI registry + extraction pipeline).

Each follow-on plan addresses:
- Concrete file paths, type definitions, function signatures
- Test plan (unit + integration + E2E)
- Codex review iteration to PASS
- Migration / backfill (if any)
- Telemetry / observability

---

## 10. Open questions (deferrable to follow-on plans)

1. **Median vs mean vs weighted** for industry-median row: configurable per-metric or single global default? Decided in Track A impl plan.
2. **Forward EPS confidence**: when FY3 EPS is sparse (few analysts), how do we surface uncertainty? Decided in Track A impl plan.
3. **Operating KPI extraction quality gates**: when extraction hints fail (e.g., transcript wording changed), what's the fallback — null, last-known, or fail-loud per the project's "fail loudly" pattern? Decided in Track B impl plan.
4. **Process-template migration sequencing**: which template first, what consumer-skill migration prerequisites? Decided once Track A ships and §7.4 Phase 1 is in place.
5. **Source-version pinning**: do Thesis snapshots freeze cell-level source data (full provenance) or just `source_id`s? Decided in Track 0 impl plan.

(R0 Q1 — industry-key taxonomy — moved to Track 0 scope per D9.)

---

## 11. Summary

Four coordinated tracks (one prerequisite + three feature tracks), one shared artifact contract:

- **Track 0 (prerequisite)** — schema bump v1.1 → v1.2, new `editorial_peer_set` and `operating_comparison` fields, sectioned `peer_comparison` with cell-level citation, patch ops, industry-key taxonomy, template-manifest schema, source-registry helpers.
- **Track C** — stores editorial peer sets per-thesis in the new `editorial_peer_set` field; overrides auto-discovery for both A and B.
- **Track A** — closes FMP-side gaps, ships template-shaped industry-comps artifact under `peer_comparison.sections`.
- **Track B** — introduces per-industry KPI registry (definitions only) and a multi-year operating-comps artifact under `operating_comparison`.

Templates are the spec, snapshotted into a code-owned manifest. SIA wiki + methodology integration is downstream skill work; this plan ensures the artifacts those skills consume are template-shaped, cited (cell-level), and contractually stable.

---
