# F147 — `THESIS_ARTIFACT_REGISTRY` Plan

**Status:** CODEX PASS R7 — architecture locked; implementation proceeds through the per-PR plans.
**Created:** 2026-05-25. **Revised:** 2026-05-25 (R6 → R7).
**Owner:** Henry.
**Per CLAUDE.md plan-first workflow:** this plan is reviewed by Codex before any code lands; implementation is via Codex per the prompts in §10.

**R6 → R7 changelog** (Codex R6 findings addressed):
- **B1 (`useThesis` points at wrong backend):** Split PR-0 endpoint usage. `useThesis(ticker)` uses the EXISTING research-content proxy at `/api/research/content/theses?ticker=...` + `/api/research/content/theses/{research_file_id}` (research endpoints, already proxied by `routes/research_content.py:195`). `useArtifactReady` uses the NEW `/api/artifacts/*` proxy for sidecar fetch/cache. PR-0 sub-scope A re-scoped accordingly.
- **NB1 (managing-risk fallback wrong affordance):** §4.0 row updated — populate affordance points at `/position-initiation` or `/allocation-review` (which actually write `position_size`); `/managing-risk` becomes the "review existing sizing" affordance only.
- **NB2 (`propsOrNull` signature/prose mismatch):** Tightened signature to `GeneratedArtifactProps | null`. Prose updated to explicitly include `partial` status returning `props` (matches code).
- **NB3 (§3.7 "render router" stale):** Comment in file layout cleaned — `index.ts` is "central registries map + getArtifactDescriptor + propsOrNull adapter" (no "render router" in F147 v1).
- **NB4 (`useArtifactReady` returns sidecar):** Hook contract clarified — returns the fetched **sidecar JSON payload** (typed-contract content) plus event metadata. Builders consume the sidecar payload; the event tells them when to refetch.

**R5 → R6 changelog** (Codex R5 findings addressed):
- **B1 (`<any, any>` defaults to wrong R):** Introduced `AnyArtifactDescriptor = ArtifactDescriptor<any, any, any>` named alias; `REGISTRIES` + `getArtifactDescriptor` use it for heterogeneous lookups.
- **B2 (stale §7.1 namespace sample):** Removed contradictory sample showing `ctx[descriptor.namespace]` and `ArtifactRenderer`. Section keeps only the corrected thesis-only sample.
- **B3 (managing_risk_card §4.2 inconsistency):** Reframed §4.2 row description to "sizing-display card (current `position_size` + writer attribution)" — removed "sell-trigger list + risk-limit-check banner" language. Honest v1 scope: this card is thin.
- **B4 (PR-1 prose uses pre-R5 contract):** Updated PR-1 description to reference three-generic `ArtifactDescriptor<C, P, R>` + remove "BuilderResult wrap" overview-migration language. File layout §3.7 cleaned similarly.
- **NB1:** §9.5 SSE fixture uses `"data_source": "fixture"` (TS-narrowed literal).
- **NB2:** §5.1 swept — `useArtifactReady` consistently flagged as PR-0 deliverable.
- **NB3:** §5.5 staleness rule made actionable — for Thesis fields without per-field `updated_at`, fall back to `decisions_log` last-write timestamp for the relevant section, or skip staleness check (with explicit "no staleness data" badge).
- **NB4:** `propsOrNull` adapter now includes runtime guard documentation (checks `result` shape, doesn't blindly access `.status`).

**R4 → R5 changelog** (Codex R4 findings addressed):
- **B1 (return-type asymmetry not type-safe):** `ArtifactDescriptor` gets a third generic param `R` defaulting to `BuilderResult<Props>`. Overview specializes to `R = GeneratedArtifactProps | null`; thesis uses default `R = BuilderResult<P>`. Code sample in §3.1 updated.
- **B2 (B6 sweep incomplete):** Full sweep of `renderArtifact` → `renderThesisArtifact` across §3.6, §7.1, §14. `descriptor.namespace` removed from §7.1 sample.
- **B3 (SSE fixture fields wrong):** §9.5 test fixture corrected to `{ type, skill_run_id, ticker, skill, artifact_id, artifact_path, binary_artifact_path, contract_name, data_source, ts }` matching `events.py:49` exactly. `source_path` removed (sidecar-only).
- **B4 (managing-risk decisions_log claim overstated):** Card downgraded — reads ONLY `position_metadata.position_size` from Thesis. Removed `decisions_log` read. Optional follow-up: managing-risk skill update to call `thesis_append_decisions_log` (out of F147 scope).
- **NB1:** managing_risk_card row "Frontend data source" column corrected to `useThesis(ticker)`.
- **NB2:** Swept 2 remaining "existing" claims for `useArtifactReady` / `useThesis` (lines 441, 576).
- **NB3:** §9 test strategy updated — thesis builders return `BuilderResult.status === 'empty'`, not `null`.
- **NB4:** §12 cleaned of stale R3-resolved challenge prompts (overview migration, `?` skill rows).

**R3 → R4 changelog** (Codex R3 findings addressed):
- **B1 (§3 still says overview builders migrate):** Scrubbed §3.1, §3.3 of overview migration language. Overview builders stay `Props | null` throughout F147; migration deferred to PR-1b.
- **B2 (column reframe didn't carry through):** §4.0 table reworked into 4 explicit columns: `Visual owner skill` / `Artifact-ready subscription` / `Thesis fields read` / `Typical writers`. Every row populated consistently.
- **B3 (PR-0 endpoint shapes wrong):** Endpoint paths corrected to match shipped AI-excel-addin: `/api/artifacts/{ticker}`, `/api/artifacts/{ticker}/{skill}/latest`, `/api/artifacts/{ticker}/{skill}/{artifact_id}`. No generic `/list` or `/sidecar` routes.
- **B4 (F122 helper doesn't exist):** PR-0 explicitly adds `sign_user_claim_headers` helper itself (not "reuses F122"). PR-0 ships independently of F122; if F122 ships first the helper moves to a shared location.
- **B5 (§9.5 event contract wrong):** Test spec corrected to `{ type: 'artifact_ready', skill: 'critical-factors', ticker: 'PCTY', ... }` matching shipped `EventLog.ts:36` + `events.py:49`.
- **B6 (renderArtifact contradicts PR-1b deferral):** Resolved — `renderArtifact` is THESIS-NAMESPACE-ONLY in F147 v1. Overview rendering stays in `renderOverviewArtifactEntry` switch-case. Cross-namespace consumers (Block D, F148 Packs) get a partial implementation that handles thesis IDs; overview IDs route through an adapter (or are excluded from Block D v1 sessions until PR-1b). Removed `descriptor.namespace` reference from §7.1.
- **B7 (managing_risk_card has no typed contract):** Card reframed to **pure Thesis read** — `useThesis(ticker)` only, no `useArtifactReady('managing-risk', ticker)`. Reads `position_metadata.position_size` + `decisions_log` entries. The managing-risk skill writes to decisions_log as its persistence layer; the card surfaces that. No artifact_ready dependency.
- **NB1:** Swept §3.2 / §3.4 / §3.3 wording so substrate hooks are consistently named as PR-0 deliverables.
- **NB2:** §12 / §13 relabeled R3 → R4; closed-decision questions removed (PR-0 backend scope, PR-1 parallelism, fallback strategy now resolved in §10/§4.0).
- **NB3:** §3.3 BuilderResult section's "Shipped overview builders migrate by wrapping null → empty" sentence removed (contradicts PR-1b deferral).

**R2 → R3 changelog** (Codex R2 findings addressed):
- **B1 (§7.1 reopens old descriptor model):** §7.1 rewritten — removes stale `component?: ComponentType<{props}>` reference; cross-namespace consumers use the §3.6 dispatcher pattern.
- **B2 (PR-0 event parsing scope):** PR-0 expanded — chassis `ClaudeStreamTypes.ts` (add `artifact_ready` + `aggregate_ready` to `ClaudeStreamChunk` union) + `GatewayService.mapEvent` (add typed branches) BEFORE connector parsing. Without these, events drop at the chassis boundary.
- **B3 (no risk_module artifact-fetch proxy):** PR-0 now explicitly names the backend addition — new `routes/artifacts_proxy.py` mounted at `/api/artifacts/*`, mirroring AI-excel-addin's `/api/artifacts/*` endpoints with the same signed-claim auth approach used by F122's `/api/html-artifacts/*` router.
- **B4 (managing-risk wrong skill writer):** §4.0 readiness table column reframed — "Source skill" → "Primary skill + Thesis read paths (typical writers)". Cards read from Thesis fields; the writers vary. `managing-risk` card reads `position_metadata.position_size` (written by `position-initiation` / `allocation-review`) + `managing-risk` artifact-ready (sell triggers + sizing recommendation). Scope unchanged; semantics corrected.
- **B5 (financial-red-flags wrong field claim):** Same reframe as B4. `financial-red-flags` standalone skill emits `risks` + `invalidation_triggers` (verified at `financial-red-flags.md:191`). The card reads `qualitative_factors[]` (category=financial_red_flags) typically written by `position-initiation` composite, AND reads the standalone-skill `risks[]` + `invalidation_triggers[]`. Column wording corrected.
- **B6 (overview BuilderResult migration not behavior-preserving):** Overview migration DEFERRED to a separate follow-up PR (call it PR-1b) with targeted tests. PR-1 ships ONLY the new types + thesis-side scaffolding; overview rendering stays byte-equivalent with `Props | null` semantics. This unblocks PR-0/PR-1 parallelism (R2 NB4).
- **B7 (test strategy stale + missing PR-0 SSE integration test):** §9 updated — "19 IDs" → "18 IDs"; added §9.5 PR-0 SSE integration test covering full event chain (gateway SSE → chassis `GatewayService.mapEvent` → connector parsing → cache invalidation/fetch → `useArtifactReady` update → builder rebuild → renderer re-render).
- **NB1 (useThesis/useArtifactReady wording):** Swept all references to clarify these are PR-0 deliverables, NOT existing.
- **NB2 (SOURCE_OWNERSHIP freshness):** §5.5 extended — per-row source timestamps + stale-badge rules + explicit "use owner if fresh, else show stale badge" fallback semantics.
- **NB3 (`?` readiness rows need explicit fallback):** §4.0 — each `?` row now names explicit fallback behavior (defer, downgrade to scaffolding, or rely on data-from-another-writer).
- **NB4 (PR-1 can ship parallel to PR-0):** PR-1 scope tightened to substrate-independent work (types, scaffolding, registry shape); PR-0/PR-1 can ship in parallel.
- **NB5 (duplicate §3.7 + "19 IDs" stale):** Headings deduped; all stale "19 IDs" cleaned up.

**R1 → R2 changelog** (Codex R1 findings addressed):
- **B1 (data substrate gap):** Added PR-0 foundation PR shipping `useThesis(ticker)` + `useArtifactReady(skill, ticker)` + artifact fetch/cache API + `artifact_ready`/`aggregate_ready` event parsing in `chatStreamPayloads.ts`. F147 is now 11 PRs.
- **B2 (renderer dispatch contract):** Separated `ArtifactDescriptor` (build metadata only) from rendering. Added per-namespace `THESIS_RENDERER_DISPATCH` map keyed by id with renderer-context object supporting callbacks, adjacent-artifact composition, special cases — mirroring shipped `renderOverviewArtifactEntry`.
- **B3 (builder model):** Defined explicit two-layer pattern: `useThesisArtifactContext(ticker)` (hook layer — `useMemo`-wrapped) + pure `builder(context)` (selectional). PR-2 spec updated accordingly.
- **B4 (count drift):** Normalized all references to **18 entries** (5 Tier-1 single-source + 10 Tier-2 single-source + 3 aggregates). Coverage math corrected: 10+18 = 28 of ~69 ≈ **~41%**.
- **B5 (readiness overstatement):** Added entry-by-entry readiness table in §4 — skill status from SKILL_CONTRACT_MAP cited honestly per row. Acknowledges `~ partial` skills explicitly.
- **B6 (Props|null insufficient):** Defined `BuilderResult<Props>` discriminated union with variants `ready | partial | empty | loading | error`, `missingSources[]`, `reason`, affordance metadata.
- **B7 (position_card_full dedupe):** Added §5.5 source-ownership/dedupe rules — one owner per displayed concept, provenance per row, `aggregate_ready` only on view-model change.
- **NB1:** `registry.ts` corrected to 73 lines.
- **NB2:** Visual regression infra claim narrowed to Playwright; Chromatic dropped pending verification.
- **NB3:** PR-2 thin slice switched to `thesis.critical_factors_card` (typed contract already shipping via position-card aggregate; lower risk).
- **NB4:** `performance-review` placed only in v1.1 `review.*` namespace; Tier-3 reference removed.
- **NB5:** "No API changes" claim reworded — PR-0 introduces new connector/proxy + event-parsing work; v1 entries (PR-2+) are scoped to frontend-only.

**Companion docs:**
- `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` — canonical product standard governing every visual decision in this plan
- `docs/reference/VISUALIZATION_STACK.md` — implementation reference; F147 is the named extension of Layer 2 (artifact-type curation)
- `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md` — F150 audit; defines this plan's scope
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — skill → typed contract authority

**Locked design directions (entering this plan):**
1. **Hybrid per-namespace registries** with shared `ArtifactDescriptor<Context, Props>` interface + central `getArtifactDescriptor(id)` lookup that splits on namespace and dispatches (locked 2026-05-23).
2. **Two producer paths supported:** backend-generator (`core/overview_editorial/generators/*.py` → `ArtifactDirective` → editorial pipeline) AND frontend-builder (`overviewCompositionBrief.ts`-style functions consuming hook data directly). Both end up as registry entries. (Confirmed 2026-05-25 producer-path trace.)
3. **No bare artifacts.** Every artifact-producing skill must have a paired visual (the skill-artifact-visual coupling rule — `INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` §7).
4. **Excalidraw pattern killed 2026-05-23.** All visual outputs in F147 scope render via Recharts + shadcn-style components (Pattern 1 from viz stack doc).

---

## 1. Goal

Extend the shipped `OVERVIEW_ARTIFACT_REGISTRY` pattern to cover thesis-namespace artifacts. Ship **18 v1 entries** (15 single-source canonicals + 3 aggregates), each backed by a real React component, real builder function, and a source skill whose typed contract is shipped (per §4.0 readiness table — some skills are partial-typed but their key Thesis-write fields are live).

**Outcome:** visual coverage on Hank's chat surface jumps from ~14% (10 of ~69 today) to **~41% after F147 v1** (10 + 18 = 28 of ~69). Subsequent v1.1 (advisor/plan/review namespaces) brings it to ~52%.

---

## 2. Context — what's shipped today

### 2.1 Registry pattern

The existing pattern lives at `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` (73 lines, verified 2026-05-25). Today's `OVERVIEW_ARTIFACT_REGISTRY` is 7 entries.

Key shapes (verified by file read 2026-05-25):

```ts
// registry.ts:14-19
export interface ArtifactDescriptor {
  id: string;
  label: string;
  builderRef: string;
  requiresHooks: string[];
  builder: (context: OverviewArtifactBuilderContext) => GeneratedArtifactProps | null;
}

// registry.ts:1-12 — context is overview-specific today
export interface OverviewArtifactBuilderContext {
  concentrationArtifact: GeneratedArtifactProps | null;
  performanceAttributionArtifact: GeneratedArtifactProps | null;
  taxOpportunityArtifact: GeneratedArtifactProps | null;
  incomeArtifact: GeneratedArtifactProps | null;
  assetAllocationArtifact: GeneratedArtifactProps | null;
  productTypeArtifact: GeneratedArtifactProps | null;
  decisionArtifact: GeneratedArtifactProps | null;
}
```

`GeneratedArtifactProps` (`design/GeneratedArtifact.tsx:61-80`) is chart-oriented (`xLabels`, `yTicks`, `series`, `bars`, `callouts`, `referenceLines`, `tags`, `exitRamps`). Used by all 7 overview entries today. Tables in the overview context are rendered via `data-table.tsx` block primitive composed inside dedicated card components — separate code path from `GeneratedArtifactProps`.

### 2.2 Renderer dispatch

`PortfolioOverviewContainer.tsx:1685` — `renderOverviewArtifactEntry(entry)` function dispatches by `entry.id` to specific React components. Called from `:1909` and `:1935` (pre-market-context + post-market-context bucket sets). Each `id` has its own switch case → component instance.

### 2.3 Builder pattern

Two flavors in production today:

1. **Backend-generator path:** `core/overview_editorial/generators/<feature>.py` emits `ArtifactDirective` → editorial pipeline → frontend hook (e.g., `useOverviewBrief`) → context → registry `builder()` → React.
2. **Frontend-builder path:** e.g., `overviewCompositionBrief.ts:194` (`buildOverviewProductTypeSummary`), `:261` (`buildOverviewCompositionBrief`) — pure-frontend builder consuming hook data directly. No backend generator.

Both paths produce `GeneratedArtifactProps`-shaped output for the shipped overview entries.

### 2.4 Reference renderers from demo-surface (cross-repo)

`AI-excel-addin/docs/design/demo-surface-spec.md` defines 3 shipped non-overview renderers:
- `scenario-tree` (consumes `EarningsScenarios` typed contract) — single-source
- `letter-download-button` (consumes `LpLetter` typed contract + `.docx` binary) — single-source
- `position-card` (aggregates `critical-factors` + `quantifying-risk` + live `get_positions`) — **aggregate**

These do NOT use `GeneratedArtifactProps`. Each is a custom React component with its own props interface. **The registry pattern is component-agnostic** — it just maps `id` → component + builder; the component owns its own props shape.

---

## 3. Architecture — what F147 ships

**Four layers, separated by concern (revised per R1 B2/B3/B6 findings):**

1. **Descriptor** — pure build metadata. Stable, serializable, namespaced.
2. **Hook-context** — `use*ArtifactContext(ticker)` collects hook + event data into a single context object via `useMemo`.
3. **Builder** — pure selector function over context. Returns `BuilderResult<Props>` discriminated union.
4. **Renderer dispatch** — separate from descriptor. Per-namespace dispatch map keyed by id, with renderer-context for callbacks / adjacent-artifact composition / special cases.

The shipped overview pattern already separates layers 2/3 implicitly (overview builders are pure; hooks run outside in `useMemo`). F147 makes the separation explicit and adds layer 4 to support cross-namespace consumers (Block D, F148 Packs).

### 3.1 `ArtifactDescriptor` — build metadata only

The shipped `ArtifactDescriptor` couples `OverviewArtifactBuilderContext` directly and returns `GeneratedArtifactProps | null`. F147 generalizes the type parameters but keeps the descriptor pure build metadata:

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts (extended)

// R generic carries the result type explicitly per namespace.
// Overview ships R = GeneratedArtifactProps | null (legacy);
// thesis ships R = BuilderResult<Props> (new).
export interface ArtifactDescriptor<Context = unknown, Props = unknown, R = BuilderResult<Props>> {
  id: string;                                   // namespaced — 'overview.X' / 'thesis.X' / etc.
  label: string;                                // user-visible label
  builderRef: string;                           // documentation pointer
  requiresHooks: string[];                      // data dependencies (hook names; informational only)
  builder: (context: Context) => R;             // pure selector
}

// Overview registry uses the legacy nullable shape (no migration in F147 v1)
export const OVERVIEW_ARTIFACT_REGISTRY: readonly ArtifactDescriptor<
  OverviewArtifactBuilderContext,
  GeneratedArtifactProps,
  GeneratedArtifactProps | null
>[] = [ ... ];  // shipped code byte-equivalent

// Thesis registry uses the BuilderResult shape
export const THESIS_ARTIFACT_REGISTRY: readonly ArtifactDescriptor<
  ThesisArtifactBuilderContext,
  unknown,
  BuilderResult<unknown>  // per-entry props heterogeneous
>[] = [ ... ];
```

**`builder` return type — namespace-scoped (R4 correction, R5 type-safety):** New thesis-namespace builders (and future advisor/plan/review namespaces) return `BuilderResult<Props>`. **Shipped overview-namespace builders keep their `Props | null` return signature throughout F147 v1** — no migration. Overview migration is deferred to PR-1b (see §10) with targeted tests against the nullable-semantic dependencies at `PortfolioOverviewContainer.tsx:1578, 1685`.

The third generic `R` makes this asymmetry type-safe at compile time. Each registry declares its concrete `R`; consumers narrow via namespace prefix on `id`. A generic compatibility adapter `propsOrNull<P>(result: P | null | BuilderResult<P>): P | null` lives in `artifacts/index.ts` for cross-namespace consumers that need to handle both shapes (e.g., legacy code paths during PR-1b transition). Returns `props` for both `ready` AND `partial` BuilderResult states; returns `null` for `empty | loading | error` and for the raw legacy `null`. Full implementation in §3.5.

**Zero-runtime-change guarantee** for shipped overview code: `OVERVIEW_ARTIFACT_REGISTRY` byte-equivalent (only type-parameter changes). `renderOverviewArtifactEntry` continues to dispatch via its switch-case.

### 3.2 Hook-context layer — `use*ArtifactContext(ticker)`

Hook subscriptions live OUTSIDE the descriptor and OUTSIDE the builder. Per-namespace context-collector hook:

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/useThesisArtifactContext.ts (NEW)

export interface ThesisArtifactBuilderContext {
  ticker: string;
  thesis: ThesisSnapshot | null;                              // from useThesis(ticker) — see PR-0
  artifactReady: Record<string, ArtifactReadyPayload | null>; // skill_name → latest artifact_ready payload
  positions: PositionsResponse | null;                        // from get_positions for aggregate cards
  loadingStates: Record<string, 'loading' | 'ready' | 'error'>;
  // ... other shared inputs aggregates need
}

export function useThesisArtifactContext(ticker: string): ThesisArtifactBuilderContext {
  const thesis = useThesis(ticker);
  const articulation = useArtifactReady('thesis-articulation', ticker);
  const criticalFactors = useArtifactReady('critical-factors', ticker);
  // ... per-skill subscriptions
  return useMemo(() => ({ ticker, thesis, artifactReady: { ... }, ...}), [ticker, thesis, ...]);
}
```

This pattern matches `buildOverviewCompositionBrief({...})` at `overviewCompositionBrief.ts:261` — pure assembly of hook data into a context object, consumed by pure builder selectors. Confirmed via R1 review.

### 3.3 `BuilderResult<Props>` — discriminated result type

Replaces today's `Props | null`. Distinguishes loading / no-run-yet / stale / partial / error states explicitly so renderers can display the right affordance:

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts (extended)

export type BuilderResult<Props> =
  | { status: 'ready'; props: Props }
  | { status: 'partial'; props: Props; missingSources: string[]; reason?: string }
  | { status: 'empty'; reason?: string; affordance?: { skillName: string; label: string } }
  | { status: 'loading'; sources?: string[] }
  | { status: 'error'; reason: string; sources?: string[] };

export function isRenderable<P>(result: BuilderResult<P>): result is { status: 'ready' | 'partial'; props: P; missingSources?: string[] } {
  return result.status === 'ready' || result.status === 'partial';
}
```

Variants serve different UI states:
- **`ready`** — full data available
- **`partial`** — render with partial-source badges; `missingSources[]` lists which sources are absent
- **`empty`** — no data yet; surface "Run X to populate" affordance
- **`loading`** — fetch/subscription in progress; show skeleton
- **`error`** — fetch failure / contract violation; show error state with retry

**Scope note:** `BuilderResult` applies to NEW namespaces (thesis, future advisor/plan/review). Shipped overview builders keep `Props | null` for F147 v1; their migration is deferred to PR-1b. See §3.1.

### 3.4 Per-namespace registries

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-registry.ts (NEW)

export const THESIS_ARTIFACT_REGISTRY: readonly ArtifactDescriptor<
  ThesisArtifactBuilderContext,
  unknown  // unknown — per-entry props heterogeneous (not all GeneratedArtifactProps)
>[] = [
  {
    id: 'thesis.critical_factors_card',
    label: 'Critical Factors',
    builderRef: 'buildThesisCriticalFactorsArtifact',
    requiresHooks: ['useThesis', 'useArtifactReady:critical-factors'],
    builder: (ctx) => buildCriticalFactorsResult(ctx),
  },
  // ... 17 more
] as const;
```

### 3.5 Central lookup

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/index.ts (NEW)

// Heterogeneous descriptor alias — needs all three generics as `any` so the
// asymmetric `R` (BuilderResult<Props> for thesis vs GeneratedArtifactProps | null
// for overview) doesn't collapse to the default at lookup time.
export type AnyArtifactDescriptor = ArtifactDescriptor<any, any, any>;

const REGISTRIES: Record<string, readonly AnyArtifactDescriptor[]> = {
  'overview': OVERVIEW_ARTIFACT_REGISTRY,
  'thesis': THESIS_ARTIFACT_REGISTRY,
  // future: 'advisor', 'plan', 'review'
};

export function getArtifactDescriptor(id: string): AnyArtifactDescriptor | null {
  const namespace = id.split('.')[0];
  return REGISTRIES[namespace]?.find((d) => d.id === id) ?? null;
}

export function getAllArtifactIds(): readonly string[] {
  return Object.values(REGISTRIES).flatMap((r) => r.map((d) => d.id));
}

// Runtime-guarded adapter for legacy consumers that need `Props | null`
// from either an overview descriptor (which already returns that shape) or a thesis
// descriptor (which returns BuilderResult<Props>). Returns `props` for both
// `ready` and `partial` BuilderResult states.
export function propsOrNull<P = unknown>(result: P | null | BuilderResult<P>): P | null {
  if (result === null || result === undefined) return null;
  // BuilderResult discriminated union — check status field
  if (typeof result === 'object' && 'status' in result) {
    const r = result as BuilderResult<P>;
    if (r.status === 'ready' || r.status === 'partial') return r.props;
    return null;
  }
  // Already raw props (overview legacy shape)
  return result as P;
}
```

### 3.6 Renderer dispatch — separate from descriptor

Per R1 finding B2: `component?: React.ComponentType<{props}>` was too thin. Shipped `renderOverviewArtifactEntry` injects callbacks, adjacent-artifact composition, section breaks, and special cases (e.g., product-type under asset-allocation). F147 mirrors this with a dedicated dispatcher:

```ts
// frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-dispatch.tsx (NEW)

export interface RenderContext {
  onSendMessage?: (message: string) => void;
  onNavigate?: (view: string) => void;
  adjacentArtifacts?: Record<string, BuilderResult<unknown>>;  // for composite renderers
  affordances?: { runSkill?: (skillName: string) => void };
}

export type ArtifactRenderer<Props = unknown> = (
  result: BuilderResult<Props>,
  ctx: RenderContext
) => React.ReactElement | null;

export const THESIS_RENDERER_DISPATCH: Record<string, ArtifactRenderer<any>> = {
  'thesis.critical_factors_card': (result, ctx) => <CriticalFactorsCard result={result} {...ctx} />,
  'thesis.articulation_card': (result, ctx) => <ArticulationCard result={result} {...ctx} />,
  // ... 16 more
};

export function renderThesisArtifact(id: string, result: BuilderResult<unknown>, ctx: RenderContext) {
  const renderer = THESIS_RENDERER_DISPATCH[id];
  return renderer ? renderer(result, ctx) : null;
}
```

Per-namespace dispatch maps. **F147 v1 ships only `renderThesisArtifact(id, result, ctx)`** for thesis namespace — overview rendering stays in `renderOverviewArtifactEntry` switch-case (deferred to PR-1b per R2 B6). A unified `renderArtifact(id, ...)` router that handles both namespaces ships in PR-1b. Block D / F148 Packs v1 either filter to thesis IDs only or use a temporary adapter to `renderOverviewArtifactEntry` for overview IDs.

**Why separate from descriptor:** descriptors stay serializable build metadata (could later be JSON-emitted by skills); rendering is React-component-level concern that needs the React tree context.

### 3.7 File layout

```
frontend/packages/ui/src/components/dashboard/views/modern/artifacts/
├── index.ts                          # NEW — central registries map + getArtifactDescriptor + AnyArtifactDescriptor + propsOrNull adapter (NO render router in F147 v1 — that's PR-1b)
├── types.ts                          # EXISTING — extend with ArtifactDescriptor<C, P, R> + BuilderResult<P> + RenderContext + ArtifactRenderer + AnyArtifactDescriptor
├── registry.ts                       # EXISTING — overview registry (zero functional change; only the type signature widens to include R = GeneratedArtifactProps | null)
├── registry.test.ts                  # EXISTING — keep + add test for parameterized types
├── thesis-registry.ts                # NEW — F147 v1 thesis descriptors (18)
├── thesis-registry.test.ts           # NEW
├── thesis-dispatch.tsx               # NEW — THESIS_RENDERER_DISPATCH map (per §3.6)
├── thesis/                           # NEW — per-entry artifact components
│   ├── useThesisArtifactContext.ts   # hook-context collector (§3.2)
│   ├── ArticulationCard.tsx
│   ├── ConsultationSummary.tsx      # aggregate
│   ├── PositionInitiationCard.tsx
│   ├── EarningsReviewCard.tsx
│   ├── CriticalFactorsCard.tsx
│   ├── BuildModelCard.tsx
│   ├── CompetitivePositionCard.tsx
│   ├── ComparativeAnalysisCard.tsx
│   ├── DcfRelativeValuationCard.tsx
│   ├── BusinessQualityCard.tsx
│   ├── FinancialRedFlagsCard.tsx
│   ├── ForecastAssumptionsCard.tsx
│   ├── IdentifyingRiskCard.tsx
│   ├── QuantifyingRiskCard.tsx
│   ├── RiskReviewCard.tsx
│   ├── ManagingRiskCard.tsx
│   ├── ReviewCard.tsx                # aggregate
│   ├── PositionCardFull.tsx          # aggregate — extends shipped position-card
│   └── builders.ts                   # builder functions consuming hook data
```

Aggregate components are clearly named with `Summary`, `Card` is the default single-source label.

---

## 4. v1 scope — 18 thesis-namespace entries

15 single-source canonicals + 3 aggregates = **18 unique IDs**. Thesis schema fields all live (`schema/thesis.py:386-425`, verified 2026-05-25). Source-skill readiness varies — see §4.0 readiness table.

### 4.0 Entry-by-entry readiness table

Per R1 finding B5: "all sources verified live" was overstated. Per SKILL_CONTRACT_MAP statuses, several skills are `~ partial` (typed output partial; key Thesis-write paths exist but full typed-contract migration not done). F147 v1 only requires that the **Thesis-write fields the entry reads are live** — not full typed-output parity at the skill level.

Legend: `✓` shipped fully · `~` partial (key fields shipped) · `?` needs impl-plan verification

**Column semantics correction (R3 → R4):** Three roles exist, not one — they often disagree:
1. **Visual owner skill** (current "Skill" column) — the skill the card is *named after* / *belongs to* conceptually. Informational. May or may not correspond to a data source.
2. **Artifact-ready subscription** — what's in the "Frontend data source" column; shown as `useArtifactReady('skill', ticker)` when present. Many cards have NO subscription and read purely from Thesis via `useThesis(ticker)`.
3. **Typical writer(s)** — which skills typically populate the Thesis fields the card reads. Documented in each row's "Notes" column. Cards don't depend on writer identity; they consume whatever's in the Thesis fields.

The "Skill" column is **role 1 only**. Don't infer subscription from it.

| Entry ID | Skill | Skill status (SKILL_CONTRACT_MAP) | Thesis fields read | Frontend data source | Notes |
|---|---|---|---|---|---|
| `thesis.articulation_card` | `thesis-articulation` | ✓ built | `thesis.*`, `differentiated_view[]`, `catalysts[]` | `useThesis(ticker)` (PR-0) | All read fields shipped |
| `thesis.consultation_summary` | `thesis-consultation` | ✓ built | ~8 Thesis sections (composite read) | `useThesis(ticker)` (PR-0) | Aggregate — see §5 |
| `thesis.position_initiation_card` | `position-initiation` | ~ partial | `business_overview`, `qualitative_factors`, `risks`, `invalidation_triggers`, `materiality`, `differentiated_view`, `assumptions`, `monitoring.watch_list`, `catalysts`, `position_metadata` | `useThesis(ticker)` (PR-0) | All read fields live in schema; skill `~ partial` because some typed-output ops not migrated, but Thesis-write paths exist |
| `thesis.earnings_review_card` | `earnings-review` | ~ partial (v3.2) | `quantitative_framing.eps_fcf`, `assumptions[]`, `catalysts[]`, `consensus_view` | `useArtifactReady('earnings-review', ticker)` + `useThesis` | Skill emits verdict block + patch op suggestions; both render paths required |
| `thesis.critical_factors_card` | `critical-factors` | ✓ built | `materiality`, `differentiated_view[]`, `historical_coincidences[]`, `data_gaps[]`, `catalysts[]`, `risks[]` + `invalidation_triggers[]` | `useArtifactReady('critical-factors', ticker)` + `useThesis` | Already shipped via aggregate position-card; standalone view reuses contract |
| `thesis.build_model_card` | `build-model` | ✓ built | `model_insights[]`, `price_target`, model_ref | `useThesis(ticker)` (PR-0) | Schema fields live (`schema/thesis.py:424-425`) |
| `thesis.competitive_position_card` | `competitive-position` | ✓ built | `industry_analysis.{landscape, macro_overlay, structural_trends, editorial_peer_set}` | `useThesis(ticker)` | Composite 4-section read |
| `thesis.comparative_analysis_card` | `comparative-analysis` | ✓ built | `industry_analysis.peer_comparison` | `useThesis(ticker)` | |
| `thesis.dcf_relative_valuation_card` | `dcf-relative-valuation` | ✓ built | `price_target` (Thesis-level), `valuation` | `useThesis(ticker)` | `price_target` Thesis field live |
| `thesis.business_quality_card` | `business-quality-assessment` | ? (methodology unit per SIA — Thesis-write path goes via `position-initiation` composite) | `qualitative_factors[]` (category=business_quality) | `useThesis(ticker)` | **Typical writers:** `position-initiation` composite writes `qualitative_factors[]` per the BQA methodology unit. Standalone BQA skill applies methodology in execute mode; impl plan verifies whether standalone path also writes `qualitative_factors`. **Fallback:** if no qualitative_factors with category=business_quality, render `empty` with "Run `/position-initiation` or `/business-quality-assessment`". |
| `thesis.financial_red_flags_card` | `financial-red-flags` | ~ (standalone emits `risks[]` + `invalidation_triggers[]` only; explicitly NOT `qualitative_factors[]` per `financial-red-flags.md:191`) | `qualitative_factors[]` (category=financial_red_flags) + `risks[]` + `invalidation_triggers[]` | `useThesis(ticker)` | **Typical writers:** `position-initiation` writes `qualitative_factors` (financial_red_flags category); standalone `financial-red-flags` skill writes `risks` + `invalidation_triggers`. **Fallback:** if only standalone has run, render with `risks` + `invalidation_triggers` populated and `qualitative_factors` section as `partial` skeleton. If only composite has run, render with `qualitative_factors` and `risks`/`triggers` `partial`. `empty` only if all three read fields missing. |
| `thesis.forecast_assumptions_card` | `forecast-assumptions` | ~ ready (awaiting F2d + model_summarize) | `assumptions[]` | `useThesis(ticker)` | Skill `~ ready` — workbook-write step pending. v1 thesis-side read works against existing `assumptions[]` field |
| `thesis.identifying_risk_card` | `identifying-risk` | ✓ built | `risks[]`, `invalidation_triggers[]`, `data_gaps[]` | `useThesis(ticker)` | |
| `thesis.quantifying_risk_card` | `quantifying-risk` | ✓ built | `position_metadata.portfolio_fit`, per-factor `risks[]` | `useArtifactReady('quantifying-risk', ticker)` + `useThesis` | Already shipped via aggregate position-card |
| `thesis.risk_review_card` | `risk-review` | ~ partial (v2.1) | per-ticker `risks[]` + `invalidation_triggers[]` + `portfolio_fit` | `useArtifactReady('risk-review', ticker)` + `useThesis` | Skill `~ partial` — verify per-ticker Thesis-write path in impl plan |
| `thesis.managing_risk_card` | (no artifact subscription — pure Thesis read; R4/R5 correction) | ~ (advisory/markdown v1.0; no `typed_outputs_contract`. Skill writes a markdown sizing note but does NOT call `thesis_append_decisions_log` per `managing-risk.md:83,112`. `useArtifactReady` would never fire; Thesis `decisions_log` won't contain managing-risk recommendations.) | `position_metadata.position_size` (R5: removed `decisions_log` read; skill doesn't write structured log entries) | `useThesis(ticker)` only | **Typical writers:** `allocation-review`, `position-initiation` write `position_size` (managing-risk does NOT — it writes markdown only). Card surfaces current sizing state only in v1. **Fallback:** if `position_size` empty, `empty` with "Run `/position-initiation` or `/allocation-review` to size this position" (skills that actually write `position_size`). `/managing-risk` is offered separately as a "review existing sizing" affordance when `position_size` is populated but stale. **Out-of-scope optional extension:** later card version could call out to a managing-risk markdown-note lookup via memory_read to surface latest sizing rationale — requires either updating the managing-risk skill to write a typed_outputs_contract OR exposing memory_read via a new endpoint. Both out of F147 v1 scope. |
| `thesis.review_card` (aggregate) | `thesis-review` | ✓ built | `ThesisScorecard` + materiality + claims + assumptions + risks | `useArtifactReady('thesis-review', ticker)` + `useThesis` | Aggregate — see §5 |
| `thesis.position_card_full` (aggregate — extends shipped) | composite | n/a — extension | Shipped position-card sources + `assumptions`, `price_target`, `materiality` | Multiple subscriptions — see §5.5 | Source dedupe rules required (§5.5) |

**Impl-plan obligation:** before any PR ships an entry from the `?` rows, the impl plan must verify the typed-output path against the live skill file. If `business-quality-assessment` or `financial-red-flags` turn out to be advisor-no-state without Thesis writes, those entries downgrade from canonical to scaffolding (Pattern 2A) or get deferred.

**Three skills marked `~ partial` (`position-initiation`, `earnings-review`, `risk-review`)** are OK for v1 because their Thesis-write fields are shipped — what's `partial` is the typed-output migration / patch-op coverage, not the read surface F147 needs.

### 4.1 Tier 1 — highest-frequency / brand-critical (5 single-source + 1 aggregate)

`thesis.consultation_summary` is Tier 1 by frequency but is an aggregate (see §5). Listed in §4.3 only — not double-counted here.

| ID | Source skill | Render shape | Component |
|---|---|---|---|
| `thesis.articulation_card` | `thesis-articulation` | Pitch card: thesis statement banner + 4-pillar table + dated catalyst timeline | `ArticulationCard.tsx` |
| `thesis.position_initiation_card` | `position-initiation` | Full diligence card across 5+ sections | `PositionInitiationCard.tsx` |
| `thesis.earnings_review_card` | `earnings-review` | Quarter scorecard + thesis-reconciliation diff + proposed-ops list | `EarningsReviewCard.tsx` |
| `thesis.critical_factors_card` | `critical-factors` (standalone) | Materiality banner + factor ranking table + paired-risk strip | `CriticalFactorsCard.tsx` |
| `thesis.build_model_card` | `build-model` | Model summary: key drivers + sensitivity strip + executive summary + .xlsx link | `BuildModelCard.tsx` |

Per-entry Thesis read fields documented in §4.0 readiness table.

### 4.2 Tier 2 — analysis-skill canonicals (10 single-source)

| ID | Source skill | Render shape | Component |
|---|---|---|---|
| `thesis.competitive_position_card` | `competitive-position` | 4-pillar scorecard + 10-attribute grid + section panels | `CompetitivePositionCard.tsx` |
| `thesis.comparative_analysis_card` | `comparative-analysis` | Focal-vs-peers KPI matrix table + verdict banner | `ComparativeAnalysisCard.tsx` |
| `thesis.dcf_relative_valuation_card` | `dcf-relative-valuation` | Three-way valuation table (9 method-scenario cells) + triangulation spread | `DcfRelativeValuationCard.tsx` |
| `thesis.business_quality_card` | `business-quality-assessment` | Quality-factors table + per-pillar evidence rows | `BusinessQualityCard.tsx` |
| `thesis.financial_red_flags_card` | `financial-red-flags` | Red-flag checklist with severity + paired-risk rows | `FinancialRedFlagsCard.tsx` |
| `thesis.forecast_assumptions_card` | `forecast-assumptions` | Driver dictionary table + per-driver confidence indicator | `ForecastAssumptionsCard.tsx` |
| `thesis.identifying_risk_card` | `identifying-risk` | Risk register table (4 pillars) + invalidation-trigger rows | `IdentifyingRiskCard.tsx` |
| `thesis.quantifying_risk_card` | `quantifying-risk` standalone | Factor table (β / R² / window) + idio decomposition + classification banner | `QuantifyingRiskCard.tsx` |
| `thesis.risk_review_card` | `risk-review` | Per-ticker fingerprint table + cluster + factor-stability indicator | `RiskReviewCard.tsx` |
| `thesis.managing_risk_card` | `managing-risk` (sizing display only; see §4.0 notes) | Sizing display: current `position_size` + writer attribution + "Run `/managing-risk` for sizing review" affordance | `ManagingRiskCard.tsx` |

Per-entry Thesis read fields documented in §4.0 readiness table.

### 4.3 Aggregate renderers (3)

See §5 for the aggregate-controller architecture. Listed here for the scope manifest:

| ID | Tier | Sources aggregated | Component |
|---|---|---|---|
| `thesis.consultation_summary` | Tier 1 (high-frequency) | Multi-section composite read across `thesis.*` + `differentiated_view` + `quantitative_framing` + `catalysts` + `risks` + `invalidation_triggers` + `position_metadata` + `business_overview` | `ConsultationSummary.tsx` |
| `thesis.review_card` | Tier 2 | `ThesisScorecard` (artifact_ready from `thesis-review`) + live Thesis materiality + claims + assumptions + risks | `ReviewCard.tsx` |
| `thesis.position_card_full` | Tier 2 | Extends shipped `position-card` aggregate with `assumptions`, `price_target`, `materiality` (source-ownership rules in §5.5) | `PositionCardFull.tsx` |

### 4.4 Count check

- Tier 1 single-source: **5** (articulation, position-initiation, earnings-review, critical-factors, build-model)
- Tier 2 single-source: **10** (competitive-position, comparative-analysis, dcf-relative-valuation, business-quality, financial-red-flags, forecast-assumptions, identifying-risk, quantifying-risk standalone, risk-review, managing-risk)
- Aggregates: **3** (consultation_summary, review_card, position_card_full)
- **Total: 18 unique IDs**

Matrix scope statistic to update: was "16 thesis canonical + 3 aggregate"; correct count is "15 single-source + 3 aggregates = 18 total". Updated in §14 acceptance criteria.

---

## 5. Aggregate-renderer pattern — formalized

Per `AI-excel-addin/docs/design/demo-surface-spec.md` §2.2 (shipped 2026-05-20). The pattern:

```
Aggregate-renderer-controller (component)
  ├── subscribes to source A (artifact_ready event OR hook data)
  ├── subscribes to source B
  └── subscribes to source C

On any source update:
  rebuild view-model from latest available sources
  render with partial-source badges for any missing sources
  emit aggregate_ready event (separate event since aggregates have no persisted artifact_path)
```

### 5.1 Subscription mechanism

Two flavors per source:
1. **Artifact-ready subscription** — wraps the `useArtifactReady(skillName, ticker)` hook **introduced in PR-0**. Updates view-model on each `artifact_ready` for that skill.
2. **Live-hook subscription** — uses existing data hooks (`useThesis`, `usePositions`, etc.). Updates view-model on hook data change.

Aggregate components compose multiple subscriptions; the registry entry's `builder` reads from a combined context that includes all sources.

### 5.2 Partial-source rendering

Per `INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` §5 (LLM artifact rules) and §6 (UI implications), partial-source rendering must:
- Show available sources fully rendered
- Show missing sources as "—" with a "Run X to populate" affordance pointing at the source skill name
- Never hide the existence of a missing source (would mislead user about what's known)

### 5.3 `aggregate_ready` event (cross-repo)

Per demo-surface §2.3, aggregate controllers emit `aggregate_ready` events on every view-model rebuild. F147 components consume the event for downstream chained renderers + Block D session-summary inclusion.

**Cross-repo touch:** The `aggregate_ready` event TS shape lives in `AI-excel-addin/packages/agent-gateway` (or wherever the event contract sits today). F147 components subscribe; the event itself is shipped. Verify on impl-plan round whether F147 emits new aggregate IDs that need event-schema updates (likely no — `aggregate_ready` is generic).

### 5.4 The 3 aggregate entries in detail

#### `thesis.consultation_summary`

Source roster:
- `thesis-consultation` artifact_ready (when skill last ran)
- Live `useThesis(ticker)` hook for current state of all Thesis sections

View-model:
- Section-header strip for ~8 sections
- Per-section: 1-line summary + last-updated indicator + "expand" affordance
- Diff-since-last-consultation overlay on sections that changed in the most recent skill run

Partial-source rules:
- All Thesis sections optional; render skeleton "No data yet — run `/thesis-consultation`" for empty Thesis
- Per-section: render available, "—" for missing

#### `thesis.review_card`

Source roster:
- `thesis-review` artifact_ready (ThesisScorecard)
- Live `useThesis(ticker)` for current materiality + claims + assumptions + risks

View-model:
- Scorecard table (claims × evidence × verdict) from ThesisScorecard
- Proposed-ops list with diff preview (from skill's `ops:` block)
- Materiality + claim-set context cards (from live Thesis)

Partial-source rules:
- Renders only when ThesisScorecard exists; below that, "Run `/thesis-review` to populate" full-card placeholder

#### `thesis.position_card_full`

Source roster (extends shipped `position-card`):
- `critical-factors` artifact_ready
- `quantifying-risk` artifact_ready
- Live `get_positions(format="agent")`
- NEW: live `useThesis(ticker)` for `assumptions`, `price_target`, `materiality`

View-model:
- Shipped position-card baseline (current weight + thesis-drift + sizing-vs-cap)
- NEW section: top-3 critical-factor assumptions with current confidence
- NEW section: PriceTarget range + implied return banner

### 5.5 Source ownership & dedupe rules (`position_card_full` and other multi-source aggregates)

Per R1 finding B7: adding live Thesis fields to an aggregate that already consumes other-skill artifacts can double-surface the same evidence. `position-card` today derives **thesis drift** from `critical-factors` and **sizing context** from `quantifying-risk`. Adding `useThesis(ticker)` directly could re-surface materiality / assumptions / risk-pairing that already flow through those skills' artifacts.

**Ownership rule:** one source per displayed concept. Per concept, declare in code:

```ts
// thesis/PositionCardFull.tsx (or builders.ts)

const SOURCE_OWNERSHIP: Record<DisplayedConcept, SourceId> = {
  'thesis_drift_summary': 'critical-factors',           // from artifact_ready
  'sizing_vs_cap': 'quantifying-risk',                  // from artifact_ready
  'current_weight': 'live_get_positions',                // live tool
  'top_assumptions': 'thesis.assumptions',               // live Thesis read — NEW
  'price_target_range': 'thesis.price_target',           // live Thesis read — NEW
  'materiality_threshold': 'thesis.materiality',         // live Thesis read — NEW
};
```

**Dedupe behaviors:**
1. **Render once per concept** — if both `critical-factors` artifact and `thesis.materiality` Thesis field contain materiality data, the renderer reads ONLY from the owner declared above.
2. **Provenance per row** — each rendered row carries a `source` field shown in a tooltip / chip ("via critical-factors", "via Thesis live"). Lets the user trace evidence to its declared owner.
3. **`aggregate_ready` emission** — emitted on view-model REBUILD, not every React render. Use shallow-equality check on the rebuilt view-model; suppress if identical to last emit.
4. **Conflict resolution** — when the declared owner is missing but another source has overlapping data, render `partial` status with `missingSources: ['critical-factors']` and surface only the explicitly-owned fields from secondary sources. Do not silently fall back.

**Cross-aggregate consistency:** `thesis.review_card` and `thesis.consultation_summary` may both surface `materiality`. Each declares its own ownership map; the renderers don't interfere (different cards, different surfaces). But within a single card, ownership is exclusive.

**Staleness handling (per R2 NB2):** declared-owner-wins only applies if the owner's data is *fresh*. Per `AI-excel-addin/docs/design/demo-surface-spec.md:284`, aggregate view-models include stale-source metadata. F147 aggregate view-models must:

- **Per-source timestamps** — each rendered row carries the source's `updated_at` (from artifact_ready timestamp or Thesis field's last-write timestamp where available).
- **Stale-badge threshold** — sources older than 24h (configurable) render with a stale badge / chip. Threshold per source type defined in §5.5 SOURCE_OWNERSHIP map.
- **Fallback rules when owner is stale:**
  1. If `position_card_full` owner-of-`materiality` is `critical-factors` artifact and it's >24h old but Thesis `materiality` was written today, render Thesis value WITH a "via Thesis (newer than `critical-factors` artifact)" provenance chip.
  2. Never silently swap owners; the swap is always visible.
- **`aggregate_ready` emission** still suppresses on shallow-equal rebuilds; staleness changes ARE non-equal rebuilds (timestamp changes the view-model).

Impl-plan obligation: define the full `SOURCE_OWNERSHIP` mapping AND per-source stale thresholds for all 3 aggregates before PR-10 ships.

---

## 6. Producer-side paths — both supported

Per locked design direction §2, two paths produce registry entries:

### 6.1 Backend-generator path

Used by 5 of 7 shipped overview entries. Flow:

```
core/overview_editorial/generators/<feature>.py
  → emits ArtifactDirective(artifact_id="overview.X")
  → editorial pipeline pickup
  → frontend useOverviewBrief hook
  → context.XArtifact (GeneratedArtifactProps)
  → registry builder() returns context.XArtifact
  → renderer dispatch in PortfolioOverviewContainer
```

### 6.2 Frontend-builder path

Used by `overview.composition.product_type` and `overview.decision` today. Flow:

```
frontend/packages/ui/src/components/dashboard/views/modern/overviewCompositionBrief.ts
  → buildOverview<X>Artifact(positionsHookData) → GeneratedArtifactProps
  → injected into OverviewArtifactBuilderContext via composite buildOverviewCompositionBrief
  → registry builder() returns context.XArtifact
  → renderer dispatch
```

### 6.3 F147 v1 path choices per entry

**Most thesis entries should use frontend-builder path.** Reasoning:
- Thesis state is consumed via the `useThesis(ticker)` hook **introduced in PR-0**
- Builder = pure function over hook data + skill's last artifact_ready payload
- No new editorial pipeline needed
- Matches the demo-surface renderer pattern (3 shipped renderers all use this path: read artifact_ready payload + apply view-model derivation in React)

**Backend-generator path remains available** for entries that need editorial-pipeline-orchestrated artifacts (cross-skill composition done server-side). None of F147 v1's 18 entries fall in this category — all are direct reads of skill artifact_ready + Thesis state.

---

## 7. Cross-namespace consumers — how Block D + F148 Packs use this

### 7.1 Block D (session summary — `AI-excel-addin` spec not yet written)

Block D will be a runtime-generated `ArtifactComposition` (ordered list of artifact_ids + section metadata). It consumes the central lookup.

**For F147 v1 (R4 correction, R5/R6 sweep):** F147 v1 ships only `renderThesisArtifact(id, result, ctx)`. Overview rendering stays in `renderOverviewArtifactEntry` switch-case at `PortfolioOverviewContainer.tsx:1685` (deferred to PR-1b per R2 B6). Cross-namespace consumers (Block D session summary, F148 Packs) handle overview IDs via the existing `renderOverviewArtifactEntry` adapter path or are filtered to thesis-only inputs in v1.

```ts
import { getArtifactDescriptor } from '.../artifacts';
import { renderThesisArtifact } from '.../artifacts/thesis-dispatch';

function renderSessionSummary(composition: ArtifactComposition, ctx: AllContexts) {
  return composition.entries.map(entry => {
    const descriptor = getArtifactDescriptor(entry.artifact_id);
    if (!descriptor) return null;
    const ns = entry.artifact_id.split('.')[0];
    if (ns !== 'thesis') return null;            // overview routes elsewhere until PR-1b
    const result = descriptor.builder(ctx.thesis); // thesis context
    return renderThesisArtifact(entry.artifact_id, result, renderContext);
  });
}
```

Descriptors stay pure build metadata. NO `component?` field on the descriptor. NO `descriptor.namespace` field (callers split on `id` prefix). NO unified `renderArtifact(id, ...)` router in F147 v1 — it ships in PR-1b alongside overview migration.

### 7.2 F148 Packs

Per `VISUALIZATION_STACK.md` (Layer 3) and the locked F148 sequencing decision: F148 ships AFTER Block D as a curation/transformation layer on top of `ArtifactComposition`. F148 consumes `getArtifactDescriptor(id)` identically; Pack templates select a subset of IDs in a defined order.

---

## 8. v1.1 + deferred scope

### 8.1 v1.1 (next ship after v1)

New registries (same pattern, different namespace):

- **`advisor.*`** (5 entries) — `acquisition-strategy-analysis`, `debt-sensitivity-analysis`, `dilution-analysis`, `metric-trend-analysis`, `peer-comparison-analysis` (all advisor-no-state per Tier-4 audit)
- **`plan.*`** (2 entries) — `plan-create` (investment plan summary card), `plan-review` (delta card)
- **`review.*`** (1 entry) — `performance-review` (trade scorecard card; new namespace candidate; may fold into `portfolio.*`)

Trivial extension: add a new `xxx-registry.ts` file + one line in the `REGISTRIES` map in `artifacts/index.ts`. No changes to the descriptor interface, lookup function, or shipped overview/thesis code.

### 8.2 Tier 3 (v2 candidates)

- Sub-section / composite-cell renderers from F150 matrix (industry-landscape, industry-macro-overlay, structural-trends, post-comps-landscape-refresh, peer-curation, monitoring-init, ownership-refresh, decision-log, thesis-link when shipped)
- First-class table descriptor types (formal `TableDescriptor` similar to `GeneratedArtifactProps` but for tables — separate from per-entry components)
- (`performance-review` removed from Tier 3 per R1 NB4 — placed in v1.1 `review.*` namespace above, single bucket.)

### 8.3 Out of scope forever (under current product direction)

- Pattern 2B Excalidraw / node-and-arrow diagrams (killed 2026-05-23; re-trigger condition only on irreducibly-graph data model)
- Headless agent-UI orchestration packages (CopilotKit / AG-UI / etc.) — different category

---

## 9. Test strategy

### 9.1 Unit per entry

For each of the 18 entries:
1. **Builder test** — given mocked hook data + artifact payload, thesis builders return `BuilderResult` of the expected variant (`ready` / `partial` / `empty` / `loading` / `error`) with correct `props` payload (or `missingSources` for partial). Per-entry tests cover at least the `ready` and `empty` variants. (Overview builders keep `Props | null` semantics through PR-1b; tests for those don't change.)
2. **Component snapshot test** — given props, component renders to expected DOM structure (use existing snapshot infra).
3. **Empty-state test** — component handles `null`/missing props gracefully.

### 9.2 Aggregate integration test

For each of the 3 aggregates:
1. **Single-source test** — aggregate renders correctly when ONE source has data; others show "Run X" affordances.
2. **All-sources test** — aggregate renders correctly with all sources populated.
3. **Source-update test** — aggregate rebuilds view-model when any source's data changes.

### 9.3 Registry-shape test

- `registry.test.ts` (existing) — add parameterized-type compile check.
- `thesis-registry.test.ts` (NEW) — verify all 18 IDs are unique, namespaced correctly, and `getArtifactDescriptor(id)` returns the right descriptor.
- `cross-namespace.test.ts` (NEW) — verify `getArtifactDescriptor` correctly routes between overview and thesis namespaces; unknown namespace returns `null`.

### 9.4 Visual regression

Use existing Playwright infra (Chromatic claim dropped per R1 NB2 — needs verification before relying on it). One baseline per entry. If Chromatic is in fact unavailable, fall back to Playwright screenshot snapshots or skip visual regression in v1 (test only render shape via component snapshots). Impl plan confirms tooling.

### 9.5 PR-0 SSE integration test (per R2 B7)

**Acceptance gate for PR-0.** Cover the full event chain end-to-end:

1. Send a synthetic `artifact_ready` SSE event matching the shipped gateway contract exactly:
   ```json
   {
     "type": "artifact_ready",
     "skill_run_id": "...",
     "ticker": "PCTY",
     "skill": "critical-factors",
     "artifact_id": "...",
     "artifact_path": "...",         // path to JSON sidecar
     "binary_artifact_path": null,    // null for typed artifacts
     "contract_name": "CriticalFactors",
     "data_source": "fixture",          // TS-narrowed to "live" | "fixture" per EventLog.ts:11
     "ts": 1234567890
   }
   ```
   Field shape verified against `AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49` (Python emitter) and `AI-excel-addin/src/taskpane/state/EventLog.ts:36` (TS consumer). The discriminator is `type`, NOT `event`; the payload is FLAT (no nested `payload` wrapper). `source_path` belongs in the sidecar JSON, NOT the `artifact_ready` event. Current `GatewayService.parseSSEEvent` only recognizes JSON with a `type` field — test must match this exactly.
2. Assert `GatewayService.mapEvent` returns a typed `ClaudeStreamChunk` of variant `artifact_ready` (not `null`).
3. Assert chassis `parseClaudeStreamChunk` propagates the chunk through the stream.
4. Assert connector-side `chatStreamPayloads.ts` handles the chunk (no unhandled-event warning).
5. Assert `useArtifactReady('critical-factors', 'PCTY')` hook returns the payload.
6. Assert a dependent component (use `thesis.critical_factors_card` from PR-2 as the consumer; OR a minimal test consumer if PR-0 ships before PR-2) re-renders with the new payload.
7. Repeat for `aggregate_ready` event variant.

This test belongs in PR-0 acceptance gate; if it fails, the substrate is incomplete and downstream PRs are blocked.

---

## 10. PR sequencing

**11 PRs.** PR-0 ships the data substrate (per R1 finding B1); PR-1 ships the descriptor + dispatch + result-type foundation; PR-2 through PR-10 add the 18 entries.

### PR-0: Data substrate — full event chain + Thesis hook + artifact-fetch proxy

**Per R1 B1 + R2 B2/B3.** F147 entries depend on Thesis state + skill artifact_ready events on the frontend. Neither is shipped. PR-0 ships the substrate — full event chain end-to-end, NOT just connector-level parsing.

**Sub-scope A — Backend endpoint surface (R3 B3 + R6 B1):**

Two distinct backend paths for two distinct data sources:

**A.1 — Thesis snapshot path (USE EXISTING research-content proxy):**

Thesis snapshots are NOT artifacts — they live behind the research endpoints at `AI-excel-addin/api/research/routes.py:1659`:
- `GET /api/research/theses?ticker=...` — list/lookup theses by ticker (returns research_file_id)
- `GET /api/research/theses/{research_file_id}` — fetch full ThesisSnapshot

These are ALREADY proxied through risk_module's `routes/research_content.py:195` which forwards `/api/research/*`. **PR-0 does NOT add new endpoints for Thesis reads.** `useThesis(ticker)` consumes the existing research-content proxy via the existing `/api/research/content/theses?ticker=...` + `/api/research/content/theses/{research_file_id}` paths.

**A.2 — Artifact sidecar fetch path (NEW proxy):**

Skill artifact_ready events carry an `artifact_id` + `artifact_path`. Builders need the sidecar JSON payload at that path. Today's risk_module proxies don't expose this. PR-0 ships:

- **NEW `routes/artifacts_proxy.py`** mounted at `/api/artifacts/*`, mirroring AI-excel-addin's artifact API surface (verified against `server.py:1023`):

- **NEW `routes/artifacts_proxy.py`** mounted at `/api/artifacts/*`, mirroring AI-excel-addin's actual artifact API surface (verified against `server.py:1023`):
  - `GET /api/artifacts/{ticker}` — list artifacts for a ticker
  - `GET /api/artifacts/{ticker}/{skill}/latest` — fetch latest artifact for `(ticker, skill)`
  - `GET /api/artifacts/{ticker}/{skill}/{artifact_id}` — fetch specific artifact by id
- Signed-claim auth approach matching F122 (`X-Agent-Claim-*` headers verified by `_verify_signed_user_claim`).
- **NEW `sign_user_claim_headers` helper in `utils/agent_claim.py`** — wraps the existing `sign()` primitive to produce HTTP-header-keyed output (`X-Agent-Claim-*` headers). PR-0 adds this helper directly; F122 will reuse the same helper when it lands. If F122 ships first, the helper moves to a shared location — coordinate at impl-plan time. NOT a hard dependency on F122 ship order.
- Per-user rate limiting + structured logging on the new router (60/min list, 120/min content per F122 convention).

**Sub-scope B — Chassis-side event typing (NEW per R2 B2):**

Today, `artifact_ready` and `aggregate_ready` events drop at the chassis boundary:
- `ClaudeStreamChunk` discriminated union at `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts:1` has no `artifact_ready` / `aggregate_ready` variants.
- `GatewayService.mapEvent` at `frontend/packages/chassis/src/services/GatewayService.ts:437` returns `null` for unhandled event types.

PR-0 must extend BOTH before connector-level parsing can reach `chatStreamPayloads.ts`:
- Add `artifact_ready` + `aggregate_ready` variants to `ClaudeStreamChunk` union with proper field typing (mirror AI-excel-addin's `ArtifactReadyEvent` + `AggregateReadyEvent` shapes — confirmed shipped per R1).
- Add typed branches to `GatewayService.mapEvent` that translate raw SSE event payloads into the typed `ClaudeStreamChunk` variants.

**Sub-scope C — Connector-side parsing + hooks:**

After chassis types/mapping land:
- Extend `chatStreamPayloads.ts` to handle `artifact_ready` / `aggregate_ready` chunks (route to cache + invalidation).
- **`useThesis(ticker)` hook** at `frontend/packages/connectors/src/features/thesis/useThesis.ts` (new). Fetches via existing research-content proxy: first `GET /api/research/content/theses?ticker=...` (returns list sorted by `updated_at DESC` per `AI-excel-addin/api/research/repository.py:2198`; hook takes the first/latest item), then `GET /api/research/content/theses/{research_file_id}` for the ThesisSnapshot. Returns `ThesisSnapshot | null` with loading + error states. No new backend route needed.
- **`useArtifactReady(skillName, ticker)` hook** at same package (new). Two-part responsibility:
  1. Subscribes to the SSE stream (via chassis-typed events) and tracks the latest `artifact_ready` event for `(skillName, ticker)`.
  2. On each event, fetches the **sidecar JSON payload** via the NEW `/api/artifacts/{ticker}/{skill}/latest` (or `/{artifact_id}` for pinned reads).
  Returns the FETCHED sidecar payload (typed-contract content the builder consumes) plus event metadata (`skill_run_id`, `artifact_id`, `ts`). Builders read the sidecar payload; the event metadata is for diagnostics + cache invalidation. Maintains an in-memory cache keyed by `(skillName, ticker, artifact_id)`.
- **`useDiligenceState(researchFileId)` integration** — document overlap if any; PR-0 layers `useThesis` without replacing.

**Acceptance:**

1. `useThesis('PCTY')` returns a non-null `ThesisSnapshot` when a Thesis exists for that ticker — fetched via the EXISTING research-content proxy at `/api/research/content/theses?ticker=PCTY` then `/api/research/content/theses/{research_file_id}`. No new backend route.
2. `useArtifactReady('critical-factors', 'PCTY')` returns the FETCHED sidecar payload + event metadata. Sidecar fetched via the NEW `/api/artifacts/{ticker}/{skill}/latest` route. Refreshes on each new SSE event.
3. `ClaudeStreamChunk` union includes `artifact_ready` + `aggregate_ready` variants; `GatewayService.mapEvent` returns these for the corresponding raw events (no longer `null`).
4. `chatStreamPayloads.ts` has typed branches for both events; no unhandled-event console warnings.
5. **PR-0 SSE integration test** (per R2 B7 + §9.5): sends a synthetic `artifact_ready` SSE event through the chassis stream, asserts the typed `ClaudeStreamChunk` propagates, asserts `useArtifactReady` hook updates with the payload, asserts a dependent component re-renders.
6. Existing diligence rendering paths continue to work (no regressions).

**Cross-repo touch:**
- Verify AI-excel-addin `ArtifactReadyEvent` + `AggregateReadyEvent` TS shapes against new chassis types (hand-mirror with per-repo parity tests per F122 convention).
- Confirm artifact storage endpoint paths against AI-excel-addin's `/api/artifacts/*`.

### PR-1: Foundation — descriptor + dispatch + BuilderResult (substrate-independent, ships parallel to PR-0)

**Per R2 B6 + NB4.** Scope tightened to types + thesis-side scaffolding only — no overview behavior change. Can ship parallel to PR-0.

Ships:
- Extend `ArtifactDescriptor<Context, Props, R = BuilderResult<Props>>` to the three-generic form (per §3.1). Overview specializes `R = GeneratedArtifactProps | null` so shipped builders type-check unchanged.
- Add `BuilderResult<Props>` discriminated union + `isRenderable` helper + supporting types (`RenderContext`, `ArtifactRenderer<P>`, `AnyArtifactDescriptor`, `propsOrNull` adapter).
- Create `artifacts/index.ts` with `REGISTRIES` map + `getArtifactDescriptor` + `getAllArtifactIds` (initially populated with `overview` namespace only via re-export — same byte output).
- Create empty `thesis-registry.ts` + `thesis-dispatch.tsx` files (skeleton, no entries yet).
- All existing tests continue to pass — overview builders' return types remain `GeneratedArtifactProps | null` (no BuilderResult migration).

**NOT in PR-1 (deferred per R2 B6):**
- Overview builders are NOT migrated to `BuilderResult` shape in PR-1. They keep their `Props | null` return signature. Migration deferred to **PR-1b (separate follow-up PR)** after F147 v1 ships, with targeted tests against the nullable-semantic dependencies at `PortfolioOverviewContainer.tsx:1578, 1685` (directives, exit ramps, partial-perf rendering, asset-allocation/product-type adjacency).
- Why deferred: R2 B6 found that overview rendering depends on nullable `entry.artifact` semantics in several non-trivial ways. Touching this is risky; F147 v1 doesn't need it. Cross-namespace consumers can call a thin adapter `propsOrNull(result)` that returns `result.props` for `result.status === 'ready' | 'partial'` and `null` otherwise (full impl in §3.5).

Acceptance: `getArtifactDescriptor('overview.concentration')` returns descriptor with original return type; new exports (BuilderResult, ArtifactRenderer, etc.) available for PR-2 consumption; overview rendering byte-identical.

### PR-2: Thin slice — `thesis.critical_factors_card` end-to-end

**Per R1 NB3 — switched from `thesis.articulation_card` to `thesis.critical_factors_card`** because critical-factors has the typed contract already shipped via the position-card aggregate (reuses the `CriticalFactor[]` payload + materiality field), reducing first-PR risk.

Scope:
- Create `thesis-registry.ts` with ONE entry: `thesis.critical_factors_card`.
- Create `thesis/CriticalFactorsCard.tsx` component.
- Create `thesis/useThesisArtifactContext.ts` (initial — collects `useThesis` + `useArtifactReady('critical-factors', ticker)`).
- Create `thesis/builders.ts` with `buildCriticalFactorsResult(ctx): BuilderResult<...>`.
- Create `thesis-dispatch.tsx` with `THESIS_RENDERER_DISPATCH` map (one entry).
- Register thesis namespace in central `REGISTRIES` map.
- Add `thesis-registry.test.ts` + builder + component snapshot tests + empty/partial/ready state tests.

Acceptance:
- Rendering `thesis.critical_factors_card` for a ticker with critical-factors artifact + Thesis materiality shows: materiality banner + factor ranking table + paired-risk strip.
- `partial` state shown when artifact-ready exists but Thesis materiality missing; `empty` state shows "Run `/critical-factors` to populate" affordance.
- `getArtifactDescriptor('thesis.critical_factors_card')` returns descriptor; cross-namespace router works for both overview and thesis IDs.

### PR-3 through PR-7: Tier 1 single-source entries (5 PRs, one per entry)

Each PR follows the PR-2 template: registry entry + component + builder addition to context + test.

- PR-3: `thesis.articulation_card`
- PR-4: `thesis.position_initiation_card`
- PR-5: `thesis.earnings_review_card`
- PR-6: `thesis.build_model_card`
- (PR-2 already shipped `thesis.critical_factors_card`)

That's 5 Tier-1 entries total (consultation_summary is an aggregate; see PR-10).

### PR-8: Tier 2 batch 1 (4 entries)

- `thesis.competitive_position_card`
- `thesis.comparative_analysis_card`
- `thesis.dcf_relative_valuation_card`
- `thesis.business_quality_card`

### PR-9: Tier 2 batch 2 (4 entries)

- `thesis.financial_red_flags_card`
- `thesis.forecast_assumptions_card`
- `thesis.identifying_risk_card`
- `thesis.quantifying_risk_card`

### PR-10: Tier 2 batch 3 + aggregates (5 entries)

- `thesis.risk_review_card`
- `thesis.managing_risk_card`
- `thesis.consultation_summary` (aggregate)
- `thesis.review_card` (aggregate)
- `thesis.position_card_full` (aggregate — includes §5.5 source-ownership map)

**Total: 11 PRs across 18 entries** (PR-0 substrate + PR-1 foundation + PR-2 through PR-10 entries). Tier-2 batches may be split further if individual entries get complex — the impl plan decides.

---

## 11. Cross-repo touches

### 11.1 AI-excel-addin

**Confirmed shipped (per R1 + R5 review):**
- `ArtifactReadyEvent` shipped with `artifact_id` field (verified `EventLog.ts:36`); reusable for thesis-namespace artifact IDs without contract change.
- `AggregateReadyEvent` shipped with generic `view_model_id: string` (verified `events.py:72`); new thesis aggregate IDs work without contract changes.

**Verify in PR-0 impl plan (not change):**
- Skill `artifact_ready` event emission for the 13 thesis-additions beyond the 3 shipped demo-surface skills. Spot-check a sample (e.g., `critical-factors` already shipped; verify `thesis-articulation` + `competitive-position` + `dcf-relative-valuation` emission paths).
- Artifact storage endpoint paths — confirm gateway proxy paths and signed-claim auth approach (analogous to F122's `/api/html-artifacts` router).

**No changes expected** to AI-excel-addin gateway / events / typed contracts for v1 functionality.

### 11.2 risk_module

Per R1 NB5: "no API changes" was too strong. PR-0 introduces new connector work:

**PR-0 introduces (new code):**
- `frontend/packages/connectors/src/features/thesis/` — `useThesis(ticker)` + `useArtifactReady(skillName, ticker)` hooks.
- Thesis snapshot fetch routes through the EXISTING `/api/research/content/*` proxy (verified — no new backend route needed for Thesis reads).
- `chatStreamPayloads.ts` extension — typed `artifact_ready` + `aggregate_ready` branches.

**PR-1 through PR-10 changes scoped to** `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/` and `thesis/` only. No backend changes; no new API routes; no test-harness changes beyond adding new test files.

---

## 12. Codex review brief (R5)

**R1 through R4 findings addressed** — see changelogs at top. Items below are NEW or LINGERING for R5:

**Areas to challenge:**
1. **Three-generic `ArtifactDescriptor<C, P, R>` ergonomics** — does the per-namespace `R` generic introduce friction for consumers (e.g., having to write `ArtifactDescriptor<C, P, GeneratedArtifactProps | null>` vs. defaulted `ArtifactDescriptor<C, P>`)? Or is the explicit asymmetry better than a runtime check? Verify against TypeScript variance + extraction patterns in adjacent code.
2. **`propsOrNull` adapter signature** — `propsOrNull<P>(result: P | null | BuilderResult<P>): P | null` — generic over `P` so overview consumers get `GeneratedArtifactProps | null` and thesis consumers get their entry's `Props | null`. Verify against actual cross-namespace consumer sketch.
3. **`thesis.managing_risk_card` v1 utility** — with `decisions_log` read removed, the card now shows only `position_size`. Is that meaningful as a standalone card, or does the card become too thin to ship in v1? Should it be downgraded to a metric strip in another card (e.g., embedded in `position_card_full` aggregate) rather than a standalone entry?
4. **SOURCE_OWNERSHIP staleness fallback** — §5.5 says "use owner if fresh, else show stale badge"; for `position_card_full` extending `assumptions` reads from Thesis, what defines "fresh" when Thesis has no `updated_at` per field? Is the rule actionable without per-field timestamps on Thesis?
5. **PR-0 `binary_artifact_path`** — for typed thesis artifacts, the event includes `binary_artifact_path: null`. Is the SSE test asserting null correctly, or should it skip the field? Verify against `events.py` shape.
6. **Aggregate-renderer `aggregate_ready` event emission** — §5 says aggregate controller emits `aggregate_ready` on view-model rebuilds. Verify the event TS shape against `AI-excel-addin/packages/agent-gateway/agent_gateway/events.py` `AggregateReadyEvent` — does it accept thesis-namespace aggregate IDs without contract change?
7. **`thesis.business_quality_card` writer path** — open question #4 in §13 asks whether `business-quality-assessment` standalone writes `qualitative_factors` or relies on `position-initiation` composite. Should this verification be a PR-2 acceptance gate (before the card ships), or a separate impl-plan investigation?

**Inputs available for local execution** (per CLAUDE.md memory `feedback_codex_review_encourage_local_execution`):
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` (live, 73 lines)
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx:1685` (`renderOverviewArtifactEntry` reference)
- `frontend/packages/ui/src/components/design/GeneratedArtifact.tsx:61` (`GeneratedArtifactProps`)
- `frontend/packages/connectors/src/` (existing hooks — verify whether thesis-fetch endpoint or hook exists already)
- `AI-excel-addin/schema/thesis.py:386-425` (Thesis schema — all read fields verified live)
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (per-skill `~ partial` / `~ ready` / `?` status — verify §4.0 claims)
- `AI-excel-addin/docs/design/demo-surface-spec.md` (aggregate-controller pattern + ArtifactReadyEvent + AggregateReadyEvent shapes)
- `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md` (audit deliverable)
- `docs/reference/VISUALIZATION_STACK.md` (impl reference)
- `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` (principles authority)

---

## 13. Open questions (R4)

R1 questions closed:
- ~~Aggregate ID naming convention~~ — locked to `thesis.<entry_name>_card` flat (no "aggregate" marker). Aggregates distinguished by code structure + dispatch entry, not by id-prefix.
- ~~`builder` hook subscription~~ — RESOLVED via two-layer pattern (hook-context + pure builder) per §3.2-§3.3.
- ~~`component?` field placement~~ — RESOLVED via separate `THESIS_RENDERER_DISPATCH` map per §3.6.

R3 resolved:
- ~~PR-0 backend scope~~ — RESOLVED in §10 PR-0 sub-scope A (artifacts proxy with verified endpoint paths).
- ~~PR-1 parallelism~~ — RESOLVED in §10 PR-1 (substrate-independent; ships parallel to PR-0).
- ~~`?` skill fallback strategy~~ — RESOLVED per-row in §4.0 readiness table.
- ~~Overview migration~~ — RESOLVED via PR-1b deferral (overview keeps `Props | null`; thesis uses `BuilderResult`).
- ~~Cross-namespace `renderArtifact`~~ — RESOLVED via thesis-only-in-v1 scope (see §7.1).

R4 open:
1. **Visual coverage measurement methodology** — plan claims jump from 14% → 41%. Impl plan defines measurement (count of canonical-rendered artifact IDs vs total artifact-producing skills+generators). Should this become a tracked project KPI?
2. **Tier 2 entry count split into PRs** — 10 entries split across PR-8/9/10. Some entries may merit standalone PRs if complex (e.g., `competitive-position` is composite 4-section). Impl plan refines per-entry.
3. **PR-1b scope** — when overview migration finally happens, what tests verify the nullable-semantic dependencies at `PortfolioOverviewContainer.tsx:1578, 1685` don't regress?
4. **`thesis.business_quality_card` writer verification** — impl plan must verify in code whether `business-quality-assessment` standalone skill writes `qualitative_factors[]` directly or relies on `position-initiation` composite. If standalone path doesn't write, the card stays purely a Thesis read (no `useArtifactReady` for BQA) — same shape as `managing_risk_card`.

---

## 14. Definition of done

F147 v1 ships when:

1. PR-0 through PR-10 merged (11 PRs total)
2. All 18 registry entries pass unit + aggregate integration tests
3. `getArtifactDescriptor(id)` returns correct descriptor for any `overview.*` or `thesis.*` ID
4. Renderer dispatch `renderThesisArtifact(id, result, ctx)` routes correctly for thesis namespace; overview namespace continues via `renderOverviewArtifactEntry` (cross-namespace unified router deferred to PR-1b)
5. `BuilderResult<Props>` discriminated union renders correctly for all 5 variants (ready / partial / empty / loading / error)
6. All 3 aggregates render correctly with full + partial source data; source-ownership rules (§5.5) enforced
7. PR-0 substrate verified: `useThesis(ticker)` returns Thesis snapshots; `useArtifactReady(skill, ticker)` reflects SSE events; `chatStreamPayloads.ts` parses `artifact_ready` + `aggregate_ready`
8. Visual coverage metric documented + measured: target ≥41% canonical coverage (10 shipped overview + 18 thesis = 28 of ~69 audit entries)
9. F147 TODO entry moved to `TODO_COMPLETED.md`
10. v1.1 successor TODOs filed for advisor/plan/review namespaces (single entry, references this plan)
11. Matrix doc updated: shipped entries moved from "Recommended: Canonical" to "Canonical shipped"

---

## 15. References

- `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`
- `docs/reference/VISUALIZATION_STACK.md`
- `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md`
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` (shipped pattern)
- `frontend/packages/ui/src/components/dashboard/views/modern/overviewCompositionBrief.ts` (frontend-builder reference)
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx:1685` (renderer dispatch reference)
- `frontend/packages/ui/src/components/design/GeneratedArtifact.tsx:61` (GeneratedArtifactProps)
- `AI-excel-addin/schema/thesis.py:386-425` (Thesis schema — all v1 fields live)
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (skill → contract authority)
- `AI-excel-addin/docs/design/demo-surface-spec.md` §2.2 (aggregate-controller pattern, shipped 2026-05-20)
- `docs/TODO.md` — F147 entry (this plan satisfies the "next: write plan" hook)
