# Track A — Industry Comps Artifact (Canonical Comps Framework)

**Status**: DRAFT R5 — addresses Codex R4 FAIL (1 blocker + 1 should-fix).
**Created**: 2026-05-07 (R0); revised 2026-05-07 (R1, R2, R3, R4, R5).
**Revision history**:
- R5 — addresses Codex R4 FAIL: (1) §7 still said "alongside `peer_comparison`" (stale wrapper wording from R2); reworded to "at top level alongside the other top-level fields per TA.D5 flat shape" [P1]; (2) §5 e2e integration test row said `sources[]` lets caller "persist via Track 0 patch ops" (contradicts persistence-OOS); reworded to "self-contained citation bundle (persistence-to-Thesis is OOS — see §7)" [P2].
- R4 — addresses Codex R3 FAIL: TA.D5 lock on flat additive top-level dict was inconsistent with TA.D3 / §4 / §5 / §10 wording that still implied `peer_comparison` wrapper or `(payload, sources)` tuple. R4 normalizes ALL four spots to match TA.D5: top-level shape is `{"peers": [...], "sections": [...], "industry_key": ..., "template_manifest_id": ..., "as_of": ..., "sources": [...]}` flat — no nested wrapper, no tuple. Test row explicitly asserts `set(result) == {"peers"}` flag-off byte-equivalence against existing test at `tests/mcp_tools/test_industry_peer_comparison.py:57` [P1].
- R3 — addresses Codex R2 FAIL: (1) cleared remaining "possibly new patch op" / "decided at impl" language from §4 file-changes, §9 open question 3, and §10 summary — persistence-to-Thesis is consistently OUT OF SCOPE for v1; no `RegisterSourcesOp` added [P1]; (2) restructured TA.D5 dict shape to be **strictly additive at top level** — flag-off returns `{"peers": [...]}` byte-equivalent to today's `mcp_tools/industry.py:47` output; flag-on adds new top-level fields (`sections`, `industry_key`, `template_manifest_id`, `as_of`, `sources`) alongside existing `peers`; no nested `peer_comparison` wrapper that would break existing consumers/tests [P1]; (3) corrected §6.2 source-identity language to match Track 0's actual `compute_identity_hash()` signature — identity is `{type, source_id, endpoint_or_filing_id, key_fields}` (no `provider`); `provider` is provenance metadata only [P2].
- R2 — addresses Codex R1 FAIL: (1) MCP wire contract preserved — `industry_peer_comparison()` returns a single **dict** (not tuple) with new `sources: [...]` field at top level alongside `peer_comparison: {...}`; cell IDs are call-bundle-scoped (read-only MCP semantics); persistence-to-Thesis is explicitly OUT OF SCOPE for Track A v1 [P1]; (2) producer takes `existing_sources: list[SourceRecord] = []` parameter so callers (e.g., a future handoff-assembly integration) can mint IDs against actual Thesis sources; default `[]` matches MCP read-only path with bundle-scoped IDs; eliminates ID-collision risk because `register_source()` is always called against the caller-supplied scope [P1]; (3) Track A v1 explicitly does NOT add a `RegisterSourcesOp` patch op — Track 0 didn't ship one and AI-excel-addin's `Thesis.sources[]` updates today happen via direct mutation in the handoff assembly path (`api/research/handoff.py:684-725`); persistence integration is named as a future follow-up plan, not deferred-to-impl [P1]; (4) industry-key contradiction in tests/OoS resolved — tests now assert resolver-behavior parity (whatever `resolve_industry_key()` returns is correct, including `"unknown"` when applicable); OoS clarifies "per-industry MANIFEST selection deferred to v1.1; resolved key value flows to `industry_key` field via Track 0 resolver" [P2]; (5) added TA.D12 with concrete SourceRecord candidate construction pattern (required `id` placeholder, required `text=""`, provider/endpoint/key_fields per Track 0 R4) [P2]; (6) softened cache-identity language — cache preserves logical-identity hash + `retrieved_at` (provenance); `src_N` value depends on the `existing_sources` passed to `register_source()` at call time, NOT on cache state alone [P2].
- R1 — addresses Codex R0 FAIL: (1) producer returns `(peer_comparison_payload, sources_to_register)` tuple — caller handles `Thesis.sources[]` persistence via existing assembly path or new patch op (decided at impl start by reading assembly code); cell `source_refs` are minted by `register_source()` against the candidate sources list before returning [P1]; (2) refactored `_fetch_ratios_and_estimates` to additionally return per-endpoint raw payloads (preserves provenance for source attribution); cache stores per-endpoint payloads + original `retrieved_at` (cache hit reuses same SourceRecord identity) [P1]; (3) dropped TA.D8 "no changes to compare_peers" — `compare_peers` gets an additive `editorial_peer_set` parameter; precedence: explicit `peers=` string param wins over `editorial_peer_set` (matches "manual override of override" intuition); both fall back to auto-discovery [P1]; (4) extended manifest scope — Track A's first impl phase EXTENDS `industry_comps_generic_v1.yaml` to cover the framework §4 gap-fill set (ROE, absolute Net Debt + Cash, Dividends Paid, D&A, EBIT, 2y EPS CAGR) before code starts; manifest changes commit alongside producer [P1]; (5) lazy cross-repo imports gated by feature flag — flag-off path imports zero AI-excel-addin modules; flag-off test verifies existing `mcp_tools.industry` imports work without `schema` package on PYTHONPATH [P2]; (6) cache refactor (per item 2 above) preserves per-endpoint provenance + retrieved_at — cached path produces same SourceRecord identity as fresh fetch [P2]; (7) v1 USES Track 0's `industry_resolver.resolve_industry_key(fmp_profile)` to map focal ticker to a reference industry or `"unknown"`; not unknown-always [P2]; (8) locked derived-metric `source_refs: []` with `derived: true` per framework D6 — removed from open questions [P3].
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 (Codex PASS) — see §4 for Track A scope.
**Prerequisites**:
- Track 0 (`SCHEMA_AND_PATCH_OPS_PLAN.md` R4 PASS) — SHIPPED on AI-excel-addin commit `7ce654d`
- Track C (`EDITORIAL_PEER_SET_PLAN.md` R4 PASS) — SHIPPED on risk_module commit `24af19d5`
- Both prerequisites' helpers/fields are available for consumption.

**Authoritative code references** (verified by file read 2026-05-07):
- `AI-excel-addin/config/comps_templates/industry_comps_generic_v1.yaml` (Track 0) — 6 sections, ~16 metrics, source bindings to FMP endpoints
- `AI-excel-addin/schema/source_registry.py` (Track 0) — `compute_identity_hash`, `next_source_id`, `register_source` helpers
- `AI-excel-addin/config/comps_template_loader.py` (Track 0) — `load_comps_template_manifest`, `manifest_fixture_rows`
- `AI-excel-addin/api/research/feature_flags.py` (Track 0) — `INDUSTRY_ANALYSIS_V1_2_FLAG`, `FeatureFlagDisabledError`
- `AI-excel-addin/schema/thesis_shared_slice.py` (Track 0) — `SnapshotSection`, `SnapshotMetric`, `CompMetricCell`, extended `IndustryPeerComparison`
- `risk_module/utils/peer_resolver.py` (Track C) — `resolve_peer_universe`, `EditorialPeerLike`, `PeerResolutionError`
- `risk_module/mcp_tools/industry.py:11-58` — current `industry_peer_comparison` (target of dual-write extension)
- `risk_module/fmp/tools/peers.py:128-299` — current `_fetch_ratios_and_estimates` (target of metric-coverage extension)

---

## 1. Purpose

Replace the current `industry_peer_comparison` thin reshape with a **manifest-driven, sectioned, citation-bearing artifact** matching the `industry_comps_generic_v1` template manifest.

Per Track 0 D8 (additive schema), the producer **dual-writes**:
- **Legacy `peers[]` flat list** — preserved exactly as today's `mcp_tools/industry.py` output (semantic parity)
- **New `sections[]` sectioned artifact** — populated from the manifest with cell-level citations and an industry-median row per metric

Per Track 0 D6 (write-side feature flag), the new `sections` data is only written when `INDUSTRY_ANALYSIS_V1_2_ENABLED` is on. Legacy `peers[]` is always written.

---

## 2. Audit findings (grounded by code read)

| Finding | File / location | Implication |
|---|---|---|
| `industry_comps_generic_v1.yaml` defines 6 sections + 14 base metrics + 1 derived (`pe_fy1`) via `kind: fmp_endpoint` and `kind: derived` source bindings | `AI-excel-addin/config/comps_templates/industry_comps_generic_v1.yaml` | Producer iterates sections → metrics → fetches per source binding; computes derived metrics post-fetch |
| Manifest references endpoints `income_statement_ttm`, `ratios_ttm`, `enterprise_values_ttm`, `analyst_estimates`, `key_metrics_ttm` | (manifest) | All are real FMP endpoints. `enterprise_values_ttm` is NOT currently called by `_fetch_ratios_and_estimates` — Track A adds it |
| Current `_fetch_ratios_and_estimates` fetches 7 parallel endpoints + **collapses them into one merged dict** before returning `(ticker, merged, error)`; per-endpoint payload boundaries discarded at line 267 | `fmp/tools/peers.py:128-299` | Track A REFACTORS this helper to additionally return per-endpoint raw payloads alongside the merged dict (preserves provenance). Adds `enterprise_values_ttm` to the parallel ThreadPoolExecutor batch. Function signature changes additively. |
| `_peer_metric_snapshot_cache` (15-min TTL) caches the merged dict per ticker; cache-hit path returns merged data without per-endpoint provenance or retrieved_at | `fmp/tools/peers.py:39-44, 138-140` | Cache must be REFACTORED to store `{merged_dict, raw_payloads_per_endpoint, retrieved_at}` so cache-hits produce same SourceRecord identity as fresh fetches |
| Manifest field names like `estimatedEpsAvg_fy1` are **not direct FMP fields** — they're derived (FY1 = next-year estimate from analyst_estimates list) | (manifest vs FMP API) | Producer needs a mapping layer between manifest field-names and how to extract from raw FMP responses (e.g., reuses existing `compute_forward_pe` helpers + adds FY2/FY3 analogs) |
| Manifest covers ~16 metrics (6 sections); framework R6 §4 lists gaps NOT in current manifest: **ROE, absolute Net Debt + Cash, Dividends Paid (DPS exists but not Paid), D&A, EBIT, 2-year EPS CAGR** | manifest vs framework R6 §4 | Track A extends `industry_comps_generic_v1.yaml` to cover the full §4 gap-fill set BEFORE producer impl starts |
| `IndustryPeerComparison` Pydantic shape has `peers, sections, industry_key, template_manifest_id, as_of` — but **NO `sources` field**; `Thesis.sources[]` is the registry | `AI-excel-addin/schema/thesis_shared_slice.py` (Track 0) | Producer returns `sources` as a separate top-level companion field (per TA.D5 additive top-level shape). MCP-tool callers consume bundle-scoped IDs directly (read-only). Persistence-to-Thesis is OUT OF SCOPE per §7 — a future follow-up plan integrates into `api/research/handoff.py:684-725` direct-mutation path |
| Track 0 shipped `schema/industry_resolver.py` with `resolve_industry_key(fmp_profile) -> str` per Track 0 §7 | (per Track 0 R4 plan §7 + commit `7ce654d`) | Track A v1 calls this resolver — not unknown-always |
| Current `industry_peer_comparison -> compare_peers -> _reshape_peer_comparison`; `compare_peers` does its own peer resolution at L367-405 ignoring any caller-passed editorial set | `mcp_tools/industry.py:19`, `fmp/tools/peers.py:360-405` | `compare_peers` gets additive `editorial_peer_set` parameter; precedence: explicit `peers=` str wins, then `editorial_peer_set`, then auto-discovery. Track A modifies `compare_peers` (TA.D8 dropped) |
| `register_source(sources, candidate)` returns `tuple[SourceId, list[SourceRecord]]` (per Track 0) | `source_registry.py:40` | Producer accumulates registry updates per fetch; threads through the build pipeline |
| `resolve_peer_universe(focal_ticker, editorial_peer_set)` returns `tuple[list[str], Literal["editorial","auto"]]` | `risk_module/utils/peer_resolver.py` | Producer uses helper for peer-set; replaces current `compare_peers:367-405` ad-hoc resolution |
| `IndustryPeerComparison` Pydantic model has both `peers` (legacy) and `sections` (new), both optional with defaults | `AI-excel-addin/schema/thesis_shared_slice.py` (Track 0) | Single-field dual-write — same Pydantic instance carries both shapes |
| `INDUSTRY_ANALYSIS_V1_2_FLAG = "INDUSTRY_ANALYSIS_V1_2_ENABLED"` env var; `FeatureFlagDisabledError` extends `InvalidTargetError` | `feature_flags.py:7-12` | Producer checks env var directly via `os.environ.get(INDUSTRY_ANALYSIS_V1_2_FLAG)` (or the helper if Track 0 added one) |

**Gap summary:** Track 0 shipped the schema, manifest, helpers, and patch ops. Track A is the **producer side** that wires it all together: read manifest → fetch per source binding → register sources → compute medians → assemble sectioned artifact → emit dual-write payload.

---

## 3. Locked design decisions

### TA.D1. Manifest-driven, not hardcoded
Producer reads `industry_comps_generic_v1.yaml` via `load_comps_template_manifest()` and iterates the sections/metrics. **No hardcoded metric list in code.** Adding a new metric to the manifest must add it to the artifact without code changes (assuming the source binding's `fmp_endpoint`/`fmp_field` resolves cleanly via existing FMP client).

### TA.D2. Source-binding dispatcher operates on per-endpoint payloads
A new `risk_module/fmp/tools/manifest_source_dispatcher.py` module maps each `source.kind + source.fmp_endpoint + source.fmp_field` to the right value extraction. **Operates on per-endpoint raw payloads** (not the merged dict from `_fetch_ratios_and_estimates`) — preserves which endpoint each value came from. For `kind: derived`, it post-computes from already-extracted values in the same metric collection pass.

### TA.D3. Per-ticker × per-endpoint source registration
Each unique `(ticker, endpoint)` fetch yields one `SourceRecord` registered via `register_source(sources, candidate)`. The returned `SourceId` is stamped on every metric cell whose source binding resolved through that fetch (one ticker × one endpoint = one source entry, even if 5 metrics extract from it).

**Producer return shape**: see TA.D5 — flat additive top-level dict. The `sources` field is added at the same top level as `peers`, `sections`, etc. — NOT nested under a `peer_comparison` wrapper. Sources are bundle-scoped (`src_N` IDs minted against the caller-supplied `existing_sources`, default `[]`).

**Persistence to `Thesis.sources[]` is OUT OF SCOPE for Track A v1** — see TA.D5 + §7 "Persistence-to-Thesis". MCP-tool callers consume the self-contained citation bundle directly; future handoff-assembly integration is a separate follow-up plan that wires the producer into `api/research/handoff.py:684-725`.

### TA.D4. Industry-median row computed per `aggregation` field
For each metric, after collecting peer values, compute the row aggregate per the manifest's `aggregation` field (`"median"` | `"mean"` | `"weighted"`). v1 supports `median` and `mean` only; `weighted` raises `NotImplementedError` (deferred to a follow-up; manifest doesn't currently use it). `null_policy: "skip"` excludes None values from aggregation.

### TA.D5. Strictly-additive top-level dict (preserves wire compat)
`industry_peer_comparison()` returns a **single flat dict** that EXTENDS the current top-level shape additively. Existing consumers and tests at `tests/mcp_tools/test_industry_peer_comparison.py:57` continue to find `peers` at the top level and don't break.

**Flag off** — byte-equivalent to today's `mcp_tools/industry.py:47` output:
```python
{
    "peers": [...]   # legacy flat list, unchanged shape
}
```

**Flag on** — same `peers` field plus additive top-level v1.2 fields:
```python
{
    "peers": [...],                                   # legacy flat list (unchanged shape, semantic parity)
    "sections": [...],                                # NEW — sectioned artifact per manifest
    "industry_key": <resolver_output>,                # NEW — may be "unknown" or a reference industry
    "template_manifest_id": "industry_comps_generic_v1",  # NEW
    "as_of": "<ISO date>",                            # NEW
    "sources": [SourceRecord(...).model_dump(), ...]  # NEW — bundle-scoped sources whose src_N IDs are referenced in cells
}
```

**No nested `peer_comparison` wrapper** — keeping the shape flat preserves wire compat with existing tests. Mapping to the `IndustryPeerComparison` Pydantic model is a Caller concern (whoever persists the data into Thesis can extract the peer-comparison-shaped subset cleanly: same field names, same nesting).

**ID scoping**: cell `source_refs` reference IDs that exist in this same payload's `sources` list. Caller (skill, UI, future persistence path) gets a self-contained citation graph.

**Read-only contract**: MCP-tool callers don't pass `existing_sources` — producer mints IDs against an empty list, returning bundle-scoped IDs (`src_1`, `src_2`, ...). Persistence-to-Thesis (renumbering against actual `Thesis.sources[]`) is OUT OF SCOPE for Track A v1; a future plan integrates the producer into the handoff assembly path (`api/research/handoff.py:684-725` is where `Thesis.sources[]` is mutated today via direct list extension during artifact build).

### TA.D6. Feature flag gate at producer + peer-resolution precedence
`industry_peer_comparison()` reads `INDUSTRY_ANALYSIS_V1_2_ENABLED` at call time. Helper signature:
```python
def industry_peer_comparison(
    symbol: str,
    peers: str | None = None,
    limit: int = 5,
    *,
    editorial_peer_set: list | None = None,        # NEW — Track C input (optional)
    existing_sources: list[dict] | None = None,    # NEW — for ID scoping (default empty list = bundle-scoped IDs)
) -> dict:
```

**Peer-resolution precedence** (locked):
1. If `peers=<str>` is explicitly provided → use that comma-separated list (legacy explicit-override behavior)
2. Else if `editorial_peer_set` is non-empty (post-normalization, post-focal-filter per Track C) → use it
3. Else fall back to auto-discovery via `resolve_peer_universe(symbol, editorial_peer_set=None)` — which itself does subindustry → FMP `stock_peers`

This matches "manual override of the override" intuition: `peers=` is a one-off explicit list (e.g., a CLI/skill arg); `editorial_peer_set` is the persistent thesis-level curation; auto-discovery is the default. None silently merge — explicit-wins-or-falls-back.

### TA.D7. v1 uses Track 0's `resolve_industry_key()`
Track A v1 calls `resolve_industry_key(fmp_profile)` from Track 0's `schema/industry_resolver.py` to map the focal ticker's FMP profile to a reference industry (`hr_payroll` | `grocers` | `<TBD>`) or `"unknown"`. Resolver returns `"unknown"` when no mapping exists — Track A respects that and renders via `industry_comps_generic_v1.yaml`.

Per-industry manifest selection (e.g., loading `industry_comps_hr_payroll_v1.yaml` when `industry_key == "hr_payroll"`) is **out of scope for Track A v1** — current Track 0 manifest set has only the generic. v1 always loads `industry_comps_generic_v1.yaml`. Per-industry manifest authoring is a v1.1 follow-up or Track B's domain (operating comps already industry-keyed).

### TA.D8. `compare_peers` gets additive `editorial_peer_set` parameter
`compare_peers` (`fmp/tools/peers.py:332`) gets one new optional kwarg: `editorial_peer_set: list[EditorialPeerLike] | None = None`. When provided AND `peers=<str>` not provided, peer resolution at L360-405 calls `resolve_peer_universe(symbol, editorial_peer_set)` from Track C instead of the inline subindustry-then-stock-peers logic. Existing callers (legacy code paths) pass `None` and behavior is byte-equivalent.

This avoids the previous TA.D8 contradiction: editorial peer overrides flow through the actual peer-resolution code path used by both legacy and v1.2 outputs.

### TA.D9. Lazy cross-repo imports gated by feature flag
Cross-repo imports from AI-excel-addin (`load_comps_template_manifest`, `register_source`, `resolve_industry_key`, Pydantic types like `SourceRecord`) live behind the v1.2 flag check. Module top-level imports from AI-excel-addin are **forbidden** in Track A's modified files; all such imports happen lazily inside `industry_peer_comparison`'s flag-on branch.

**Rationale**: matches Track C's Protocol-typing discipline — flag-off path imports zero AI-excel-addin modules, so existing `mcp_tools.industry` consumers continue working without any cross-repo PYTHONPATH plumbing.

A flag-off integration test verifies `import mcp_tools.industry` succeeds and `industry_peer_comparison()` returns legacy-shape payload when `schema` package is NOT on PYTHONPATH.

### TA.D10. Manifest extension before code (closes framework §4 gaps)
Track A's first impl phase EXTENDS `industry_comps_generic_v1.yaml` to cover the framework R6 §4 gap list:
- Add metrics: `roe_ltm`, `net_debt_ltm` (absolute), `cash_ltm` (absolute), `dividends_paid_ltm`, `dna_ltm`, `ebit_ltm`, `eps_2y_cagr` (derived from `eps_fy1`/`eps_fy3`)
- Update relevant section orderings
- Update fixture CSV alongside

Manifest changes commit with the producer in the same PR (cross-repo). The producer code reads the extended manifest from day one; nothing depends on the smaller v1 manifest.

### TA.D11. Cache refactor preserves provenance
`_peer_metric_snapshot_cache` is refactored to store `{merged_dict, raw_payloads_per_endpoint, retrieved_at}` rather than just the merged dict. On cache-hit:
- Merged dict reused for legacy path (byte-equivalent to today's behavior)
- Per-endpoint raw payloads available for the dispatcher
- `retrieved_at` reused (NOT updated to current time) — so SourceRecord provenance is stable across cache lifetime

**Note on `src_N` identity**: cache preserves the inputs to `register_source()` (logical-identity fields + `retrieved_at` for provenance). The actual `src_N` minted depends on the `existing_sources` list passed at registration time — it is NOT a property of the cache. Same logical source registered twice against the same `existing_sources` returns the same id (Track 0 dedupe by identity hash); registered against different `existing_sources` lists returns different `src_N` values. This is correct: id-stability is per-thesis (or per-bundle), not per-cache-entry.

Cache key remains per-ticker; TTL unchanged at 15 min.

### TA.D12. SourceRecord candidate construction pattern
Per Track 0 `SourceRecord` (required `id: SourceId`, required `text: str`):
```python
candidate = SourceRecord(
    id="src_1",                             # placeholder; register_source() rewrites to actual minted id
    type="other",                           # FMP isn't filing/transcript per Track 0 R4 enum mapping
    source_id=f"fmp:{endpoint}:{ticker}:ttm",
    text="",                                # empty for endpoint snapshots — no narrative text content
    provider="fmp",
    endpoint_or_filing_id=endpoint,         # e.g., "ratios_ttm", "enterprise_values_ttm"
    key_fields={"symbol": ticker, "period": "ttm"},
    retrieved_at=iso_now,                   # timestamp when fetch succeeded (or when cache was written)
)
src_id, updated_sources = register_source(existing_sources, candidate)
```

The placeholder `id="src_1"` satisfies the regex constraint at validation time; `register_source` overwrites with the real minted id (e.g., `src_42` if existing_sources has 41 entries). `text=""` is empty since FMP endpoint responses don't have natural narrative text — the structured value extraction is what matters; `text` is reserved for filing/transcript spans where the literal text excerpt is the citation body.

---

## 4. File-by-file changes

### risk_module (primary)

**Modified**: `risk_module/mcp_tools/industry.py`
- Add `editorial_peer_set` and `existing_sources` parameters (TA.D6)
- Return type stays **dict** with flat additive top-level fields per TA.D5 (legacy `peers` field unchanged; new fields `sections`, `industry_key`, `template_manifest_id`, `as_of`, `sources` added at same top level when flag on)
- Replace current 30-line reshape with manifest-driven assembly when flag on; legacy reshape preserved when flag off
- Lazy cross-repo imports inside flag-on branch (TA.D9)
- Source registration accumulator threaded through (TA.D3)

**Modified**: `risk_module/fmp/tools/peers.py`
- `_fetch_ratios_and_estimates` return type extended to `(ticker, merged_dict, raw_payloads_per_endpoint, retrieved_at, error)` — per-endpoint provenance preserved (TA.D2, TA.D11)
- Add `enterprise_values_ttm` to parallel fetch batch + the new metrics required by TA.D10 manifest extensions (e.g., balance_sheet_ttm for ROE/Net Debt/Cash, cash_flow_ttm for Dividends Paid/D&A)
- `_peer_metric_snapshot_cache` payload shape extended per TA.D11 (cache reads/writes updated)
- `compare_peers` gets additive `editorial_peer_set` kwarg (TA.D8); peer resolution at L360-405 delegates to `resolve_peer_universe` when editorial set provided
- Existing forward-EPS / EV-to-EBITDA computations preserved (used by both legacy and new shape)

**New**: `risk_module/fmp/tools/manifest_source_dispatcher.py`
- `dispatch_source_binding(binding, fmp_response_bundle, focal_ticker)` — maps `source.kind`/`fmp_endpoint`/`fmp_field` to the right value extraction
- Handles `kind: fmp_endpoint` (direct field lookup) and `kind: derived` (formula evaluation against already-extracted values)
- Returns `(value, source_record)` tuple

**New**: `risk_module/utils/comps_aggregator.py`
- `compute_aggregate(values: list[float | None], strategy: Literal["median", "mean", "weighted"], null_policy: Literal["skip", "zero", "fail"]) -> float | None`
- Pure function; tested independently

**New tests**: 
- `risk_module/tests/mcp_tools/test_industry_v1_2_dual_write.py` — verifies legacy `peers[]` shape preserved exactly when flag off; verifies `sections[]` populated when flag on; verifies all manifest sections/metrics present in output
- `risk_module/tests/fmp/test_manifest_source_dispatcher.py` — covers `fmp_endpoint` path, `derived` path, missing-field handling
- `risk_module/tests/utils/test_comps_aggregator.py` — covers median/mean, null-policy variants
- `risk_module/tests/integration/test_industry_comps_v1_2_e2e.py` — end-to-end with mock FMP, verifies registered sources land in returned `sources[]`, cell `source_refs` reference correct `src_N` ids

### AI-excel-addin (manifest extension — committed alongside producer)
- `config/comps_templates/industry_comps_generic_v1.yaml` — extend per TA.D10 to cover framework §4 gap list. Add: `roe_ltm`, `net_debt_ltm`, `cash_ltm`, `dividends_paid_ltm`, `dna_ltm`, `ebit_ltm`, `eps_2y_cagr` (derived). Verify all new metrics' source bindings reference real FMP endpoints (`balance_sheet_ttm`, `cash_flow_ttm`, etc.) at impl start.
- `config/comps_templates/industry_comps_generic_v1.fixture.csv` — extend with rows for new metrics (companion fixture per Track 0 §7.7)

**No source-add patch op in Track A v1.** Persistence-to-Thesis is explicitly OUT OF SCOPE per TA.D5 + §7. `Thesis.sources[]` extension via the producer is a separate follow-up plan (would integrate into `api/research/handoff.py:684-725` assembly path; would NOT add a patch op since today's path uses direct list mutation in assembly).

### Out of scope (deferred to follow-ups)
- Per-industry manifest registry (Track B's domain)
- Renderer changes (separate plan; existing dispatcher should handle sectioned shape per Track 0 schema)
- Process template migration to require `industry_analysis` (framework §7.4 — separate plan)

---

## 5. Tests

| Test file | Coverage |
|---|---|
| `tests/mcp_tools/test_industry_v1_2_dual_write.py` (new) | Flag off: output is exactly `{"peers": [...]}` (`set(result) == {"peers"}` matching existing test at `tests/mcp_tools/test_industry_peer_comparison.py:57`), peers shape byte-equivalent to current `mcp_tools/industry.py:48-57` output; flag on: output has `peers` (unchanged shape, semantic parity) PLUS new top-level fields `sections`, `industry_key`, `template_manifest_id`, `as_of`, `sources` — all at same top level (no nested `peer_comparison` wrapper); all post-TA.D10 manifest sections present; all manifest metrics populated; industry-median row present per metric; `industry_key` matches `resolve_industry_key()` resolver behavior (may be `"unknown"` or a reference industry — test asserts what resolver returns); `template_manifest_id="industry_comps_generic_v1"`, `as_of` ISO-formatted; `sources[]` populated when flag on, all cell `source_refs` resolve to entries in returned `sources[]` |
| `tests/fmp/test_manifest_source_dispatcher.py` (new) | `fmp_endpoint` source kind extracts value from response bundle; `derived` source kind evaluates formula against earlier-resolved metrics; missing field returns None (not raises); cyclic derived dependency raises; unknown `source.kind` raises |
| `tests/utils/test_comps_aggregator.py` (new) | Median of [1,2,3] → 2; mean of [1,2,3] → 2; null policy skip excludes None; null policy zero treats None as 0; null policy fail raises; weighted raises NotImplementedError (v1 deferral); empty list returns None |
| `tests/integration/test_industry_comps_v1_2_e2e.py` (new) | End-to-end with mocked FMP responses for AAPL + 4 peers; verify (a) legacy peers[] semantically matches today's output; (b) sections[] structure matches manifest; (c) sources[] returned at top level for self-contained citation bundle (persistence-to-Thesis is OOS — see §7); (d) all cell source_refs reference valid src_N ids in sources[]; (e) industry-median computed correctly for revenue_ltm |

Approximately 25-35 test cases across 4 new test files. Existing `test_industry_peer_comparison.py` tests (15 cases) must continue to pass — they cover the legacy shape parity.

---

## 6. Cross-cutting concerns

### 6.1 Caching
Existing 15-min TTL on `_peer_metric_snapshot_cache` (per `fmp/tools/peers.py:39-44`) covers per-ticker fetches. Track A's added `enterprise_values_ttm` fetch joins the same cache key (per ticker). No new cache layer.

### 6.2 Source registration semantics
Per Track 0's `compute_identity_hash()` at `AI-excel-addin/schema/source_registry.py:14-27`, identity = `{type, source_id, endpoint_or_filing_id, key_fields}`. **`provider` is NOT part of identity** — it's provenance metadata stored on the registry entry alongside `retrieved_at`.

Each unique `(type, source_id, endpoint_or_filing_id, key_fields)` tuple maps to one registry entry. Track A's dispatcher constructs a `SourceRecord` with:
- `type: "other"` (FMP — per Track 0's R4 mapping)
- `source_id: f"fmp:{endpoint}:{ticker}:ttm"` or similar opaque provider key
- `provider: "fmp"`
- `endpoint_or_filing_id: <endpoint>` (e.g., `"ratios_ttm"`)
- `key_fields: {symbol: ticker, period: "ttm"}` (matches Track 0 sketch)
- `retrieved_at: <ISO timestamp>` (provenance only — NOT identity)

### 6.3 Error handling
- Manifest-load errors propagate (caller decides surface)
- Individual metric fetch failures (e.g., `enterprise_values_ttm` unavailable for a ticker) → cell value is `None`, `source_refs: []`; metric still appears in section per `null_policy: "skip"`
- Whole-ticker failures (subject ticker can't fetch any data) → caller-facing error matching current `compare_peers:441-449` pattern
- Both editorial AND auto peer-set empty → `PeerResolutionError` from Track C resolver propagates

### 6.4 Dual-write byte-equivalence (legacy `peers[]`)
Per Track 0 D8 dual-write semantic parity: legacy `peers[]` entries written by Track A producer must match today's `mcp_tools/industry.py:48-57` output **exactly** — `{ticker, name, key_metrics, relative_position, source_refs}`. Test `test_industry_v1_2_dual_write.py` enforces byte-equivalence via fixture comparison.

### 6.5 Logging
Add structured log at producer entry: `focal_ticker`, `editorial_peer_set` source (`"editorial"` | `"auto"` from Track C resolver), `peer_count`, `flag_state`, `manifest_id`, `metrics_collected`, `metrics_with_nulls`. One line per call. Matches existing `peers.py` info-level pattern.

---

## 7. Out of scope

- **Per-industry manifest selection** — Track A v1 always loads `industry_comps_generic_v1.yaml`. The `industry_key` field on output reflects whatever `resolve_industry_key(fmp_profile)` returns (may be `"unknown"`, `"hr_payroll"`, etc. per Track 0's taxonomy). What v1 does NOT do: load a different manifest based on `industry_key`. That's v1.1 — once per-industry industry-comps manifests exist, the producer selects between manifests by `industry_key`.
- **Persistence-to-Thesis (`Thesis.sources[]` extension)** — Track A v1 returns bundle-scoped sources as a top-level `sources` field alongside the other top-level fields (per TA.D5 flat shape). Persistence to a real Thesis (renumbering source IDs against actual `Thesis.sources[]` and merging into the thesis row) is a SEPARATE follow-up plan that integrates the producer into AI-excel-addin's `api/research/handoff.py:684-725` assembly path. Track 0 did not ship a `RegisterSourcesOp` patch op; Track A v1 does not add one. The MCP tool returns self-contained citation bundles for skill/agent consumption; persistence is decoupled.
- **`weighted` aggregation strategy** — manifest schema allows it, but no current metric uses it; v1 raises `NotImplementedError`. Defer to first manifest that needs it.
- **Renderer extensions** — sectioned shape rendering is downstream; Track A's PR doesn't touch frontend
- **Process-template migration** — framework §7.4 phased rollout is its own track
- **Operating comps fields** — Track B's domain (`operating_comparison` sibling field)
- **Editorial peer-curation skill** — downstream
- **Caller migration** — existing API/skill consumers of `industry_peer_comparison` continue to receive a dict; new fields are additive. No breaking-change migration.
- **Cross-version backfill** — no backfill of historical artifacts to populate `sections[]`; it's forward-only

---

## 8. Rollout sequence

1. **Phase 1**: ship `manifest_source_dispatcher.py` + `comps_aggregator.py` + their tests (helper modules, no behavioral change)
2. **Phase 2**: extend `_fetch_ratios_and_estimates` with `enterprise_values_ttm` (additive, all existing tests pass)
3. **Phase 3**: refactor `industry_peer_comparison` to manifest-driven, dual-write, flag-gated
4. **Phase 4**: integration tests + flag-off shipping. Flag stays off in production.
5. **Phase 5** (separate PR / track): flip flag on after downstream consumers (renderer, skill) are ready

Phases 1-2 can land together. Phase 3 can land flag-off (no behavioral change). Phase 5 is gated on Tracks A/B/C all complete.

---

## 9. Open questions (deferrable to impl)

1. **Manifest field-name to FMP-response field mapping** for analyst_estimates: Track 0's manifest uses keys like `estimatedEpsAvg_fy1` but actual FMP response uses indexed list (FY1 = year[1] from estimates list, etc.). Impl resolves by extending the dispatcher to handle this convention; manifest stays as-is.
2. **`enterprise_values_ttm` endpoint signature** — verify FMP exposes this as standalone vs requiring `enterprise-values` with `period=ttm`. Adjust manifest if endpoint name differs.
3. ~~`Thesis.sources[]` persistence path~~ — closed: persistence is OUT OF SCOPE for Track A v1 per TA.D5 + §7 (no `RegisterSourcesOp`; assembly-path integration deferred to a follow-up plan). Verified at impl start by reading `AI-excel-addin/api/research/handoff.py:684-725` (today's direct-mutation path).
4. **Caching of manifest object** — Pydantic-parsed manifest can be cached at module level (immutable). Verify `load_comps_template_manifest()` is fast enough to call per request, or memoize at risk_module side.
5. **Per-industry manifest selection for v1.1** — once an `hr_payroll`-keyed industry-comps manifest exists, the producer needs to select between manifests based on `industry_key`. v1 always loads generic. Decided in v1.1 plan.

(R0 Q3 — derived-metric `source_refs` policy — locked per framework D6: empty list + `derived: true`. Removed from open questions.)

---

## 10. Summary

Track A wires **the producer side** of the canonical industry-comps artifact:

- **2 new modules** in risk_module (`manifest_source_dispatcher.py`, `comps_aggregator.py`)
- **2 modified modules** in risk_module (`mcp_tools/industry.py` — manifest-driven dual-write returning a single flat dict with additive top-level fields per TA.D5; `fmp/tools/peers.py` — added endpoints, refactored cache + return shape, additive `editorial_peer_set` kwarg on `compare_peers`)
- **Manifest extension** in AI-excel-addin (`industry_comps_generic_v1.yaml` + fixture extended for framework §4 gap list per TA.D10)
- **0 new patch ops** — persistence-to-Thesis is explicitly OUT OF SCOPE for Track A v1; future follow-up integrates producer into handoff assembly path
- **4 new test files** (~25-35 cases) including a flag-off test that imports without AI-excel-addin on PYTHONPATH
- **0 Pydantic schema changes** (Track 0 shipped them)
- **Lazy cross-repo imports** behind feature flag — flag-off path matches Track C's no-runtime-cross-repo discipline

After Track A merges (flag-off), the artifact is ready for downstream consumers. Track B follows for operating comps. Once both are flag-on, the canonical comps framework is complete for v1.

---
