# Overview Income Projection Artifact Plan

## Problem

`core/overview_editorial/generators/income.py:217-233` emits an `ArtifactDirective`
for `overview.income_projection` and a paired `MarginAnnotation` anchored to
`artifact.overview.income_projection`. The frontend `OVERVIEW_ARTIFACT_REGISTRY`
in `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts`
has no descriptor for that ID, so `PortfolioOverviewContainer.tsx:812-822`
logs a warning and drops the directive. Even if the descriptor existed, the
overview page only renders IDs that appear in `PRE_MARKET_CONTEXT_ARTIFACT_IDS`
or `POST_MARKET_CONTEXT_ARTIFACT_IDS` (container lines 220-230) **and** have an
explicit switch case in `renderOverviewArtifactEntry` (container line 1591+).
Unknown IDs hit `default: null`. The card never renders; the directive's
"Editorial/New" tag never appears; the `changedFromPrevious` ring never applies.
The margin annotation passes a looser `startsWith('artifact.')` filter and still
renders in the ChatMargin sidebar, but is spatially disconnected from a card
that does not exist.

Discovered via live brief inspection 2026-04-14 (TODO.md F34, marked Minor).

## Goal

Build the missing income projection artifact, register it, and wire it through
all three render paths (registry, bucket set, switch case) so the directive
lands and the margin annotation anchors to a visible card.

## Design — Option A: Top Income Contributors

Mirror the `overviewTaxOpportunityArtifact` pattern: bar chart of the top 4
positions by projected annual $ income, with per-row presets carrying
income/yield/weight tags.

### Data

Source: `useIncomeProjection()` from
`frontend/packages/connectors/src/features/income/hooks/useIncomeProjection.ts`.
Shape produced by `resolver/registry.ts:1128-1207`:

```ts
{
  total_projected_annual_income: number;
  portfolio_yield_on_value?: number;
  portfolio_yield_on_cost?: number;
  positions?: Array<{ ticker: string; annual_income: number; yield: number }>;
  assumptions?: { source?: string };
  // ... other fields not needed for the artifact
}
```

**Confirmed:** `yield` is percentage points (not a fraction). Backend contract at
`portfolio_risk_engine/income_projection.py:412` computes `yield_on_value =
income / market_value * 100`.

**Weight data:** Do NOT source weights from `concentrationRows` — that list is
capped to 5 by weight (`PortfolioOverviewContainer.tsx:624-627`). Top income
contributors routinely sit outside the top-5 weight slice. Build a **separate
full holdings weight map** from `positionsData?.holdings` (from `usePositions`),
which is the full holdings list. If `positionsData?.holdings` is empty (hook
still loading), fall back to `data?.holdings` (from `usePortfolioSummary`).
If both are empty, the weight map is empty and all weight tags show `pending`.
Normalize ticker casing (`.toUpperCase().trim()`) on both sides of the join so
case/whitespace differences don't produce `pending` tags.

**Filter:** Keep only contributors with `annual_income > 0`. Negative income is
theoretically possible (short positions, borrow fees netted) and should not
appear in a "top income payers" card.

**Synthetic mode handling:** The resolver's synthetic fallback path
(`resolver/registry.ts:1133-1154`) returns **no `positions` array** at all.
Under the proposed builder rules (`null` when no positions), the artifact is
suppressed in synthetic mode. This is the correct behavior — we don't want to
render made-up per-ticker data. Remove the prior plan's `"Built from: synthetic estimate"`
tag variant; it's unreachable.

### Visual shape

- **chartType**: `'bar'`.
- **bars**: top 4 positions by `annual_income` descending, `value = annualIncome`
  in $.
- **yTicks**: currency tick ladder. `buildOverviewCurrencyTicks` currently lives
  inside `PortfolioOverviewContainer.tsx:386`. **Extract only the currency
  helper** to a shared util module
  (`frontend/packages/ui/src/components/dashboard/views/modern/overviewArtifactTicks.ts`)
  and update the tax opportunity memo to import from there. Leave the two
  different percent-tick implementations where they are
  (`PortfolioOverviewContainer.tsx:367` and
  `overviewArtifactBrief.ts:50`) — they have distinct ladder rules and unifying
  them would change concentration-artifact tick behavior. That is out of scope
  here.
- **bar tone**: `'up'` uniformly.
- **presets**: one per row.
  - `id`: `'income:{ticker}'`
  - `label`: ticker
  - `target.label`: `$X,XXX/yr` (formatted via existing `formatMetricValue`
    currency formatter)
  - Tags:
    - `Annual income`: `$X,XXX`
    - `Yield`: `X.X%`
    - `Weight`: `X.X%` if known, else `'pending'`
- **artifact-level tags**:
  - `Built from`: `'live holdings'` (synthetic mode already suppressed — see
    above).
  - `As of`: `portfolioOverviewData?.summary.lastUpdated` or `'latest pull'`.
  - `Methodology`: `'annual income ranking'`.
- **claim** (lead + total):
  > "{LEAD_TICKER} is carrying ${LEAD_INCOME}/yr of the book's projected
  > ${TOTAL}/yr income stream."
  Single-contributor fallback:
  > "{LEAD_TICKER} is the only material income payer in the current book,
  > projecting ${LEAD_INCOME}/yr."
- **interpretation** (multi):
  > "Income concentration matters for durability. Use this to decide whether the
  > stream is spread across enough payers or hinges on a handful of names."
  Single-contributor fallback:
  > "With only one material income payer, the stream's durability hinges on
  > that name — treat this as a single-line concentration check, not a
  > diversified income story."
- **exitRamps**:
  - `{ label: 'Open income view', action: { type: 'navigate', payload: 'income' } }`
  - `{ label: 'Review contributors', action: { type: 'navigate', payload: 'holdings' } }`

### Rendering rules

- **Empty state**: builder returns `null` when `positions` is missing/empty or
  no contributor has `annual_income > 0`. The artifact simply does not render,
  matching how `overviewTaxOpportunityArtifact` handles an empty loss screen.
- **Directive-only gating**: The backend directive does NOT gate whether the
  card renders — the container applies directives on top of whatever the
  builder produced (`PortfolioOverviewContainer.tsx:1489`, `1522-1542`). So the
  artifact can render even when the directive is absent (i.e., yield < 2%). This
  is fine — the card itself is useful whenever income data exists. The directive
  only adds the "Editorial" tag and the `changedFromPrevious` ring on top.
- **Warning treatment**: `warning_count > 0` is already handled via attention
  items (`income.py:116-139` + `192-215`). Do NOT duplicate on this artifact.

### Position order in the rendered page

Backend directive emits `position=40`. Sorting rule in
`PortfolioOverviewContainer.tsx:1529-1536` compares directive position first,
falls back to registry index. But render order is **also gated** by the
`PRE_/POST_MARKET_CONTEXT_ARTIFACT_IDS` bucket split (lines 1803-1826).

**Decision:** Put `overview.income_projection` in
`POST_MARKET_CONTEXT_ARTIFACT_IDS` — income sits naturally alongside tax
opportunity, composition, and decision cards (portfolio-character content), not
next to concentration/performance (risk-forward content).

Registry insertion order: append after `overview.decision`. This gives it the
highest registry index, so when the directive is absent, it renders last in the
POST bucket. When the directive is present with `position=40`, it sorts relative
to other POST-bucket directives — its final position depends on what those
generators emit, and we'll verify by inspection.

## File changes

### New

- `frontend/packages/ui/src/components/dashboard/views/modern/overviewArtifactTicks.ts`
  - Export `buildOverviewCurrencyTicks` (moved from `PortfolioOverviewContainer.tsx:386-402`
    — exact code, no behavior change).
  - Currency-only; percent-tick helpers stay in place.

- `frontend/packages/ui/src/components/dashboard/views/modern/overviewIncomeArtifactBrief.ts`
  - Types:
    - `OverviewIncomeContributor`: `{ ticker: string; annualIncome: number; yieldPct: number; weight: number | null }`
    - `OverviewIncomeArtifactBrief extends OverviewArtifactEditorial`: `claim`, `interpretation`, `bars`, `rows`, `tags`, `exitRamps`, `timestamp`, `leadTicker`, `totalAnnualIncome`, `singleContributorMode`.
  - `buildOverviewIncomeArtifactBrief(input)` → `OverviewIncomeArtifactBrief | null`
    - Input: `{ contributors, totalAnnualIncome, portfolioYieldOnValue, timestamp }`
    - Returns null per empty-state rule.
  - `buildGeneratedArtifactFromOverviewIncomeBrief(brief)` → `GeneratedArtifactProps`

- `frontend/packages/ui/src/components/dashboard/views/modern/overviewIncomeArtifactBrief.test.ts`
  - null when contributors empty
  - null when all `annualIncome <= 0`
  - single-contributor claim + interpretation copy
  - multi-contributor claim names lead and total
  - presets include all three tags
  - weight `'pending'` when null
  - filters out `annualIncome <= 0` entries before taking top 4
  - yield formatted as percent (input already in percentage points)
  - `$X,XXX/yr` currency formatting in preset targets

### Modified

- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts`
  - Add `incomeArtifact: GeneratedArtifactProps | null` to
    `OverviewArtifactBuilderContext`.
  - Append descriptor (last in array):
    ```ts
    {
      id: 'overview.income_projection',
      label: 'Income Projection',
      builderRef: 'buildOverviewIncomeArtifactBrief',
      requiresHooks: ['useIncomeProjection', 'usePositions', 'usePortfolioSummary'],
      builder: (context) => context.incomeArtifact,
    }
    ```

- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.test.ts`
  - Extend fixture expectation: 7 descriptors instead of 6; new descriptor fields
    as above.

- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`
  - Import `useIncomeProjection` from `@risk/connectors`.
  - Import `buildOverviewIncomeArtifactBrief`,
    `buildGeneratedArtifactFromOverviewIncomeBrief` from the new module.
  - Import `buildOverviewCurrencyTicks` from the new shared ticks module
    (remove the local definition at line 386; update the tax opportunity memo
    at line 1035 to use the imported version). Leave `buildOverviewArtifactTicks`
    at its current location in the container.
  - Call `const incomeProjection = useIncomeProjection();` in the container body.
  - Add `POST_MARKET_CONTEXT_ARTIFACT_IDS` entry: `'overview.income_projection'`.
  - Build `overviewIncomeArtifact` via `useMemo`:
    - Build full holdings weight map: primary source `positionsData?.holdings`
      (from `usePositions`); fallback `data?.holdings` (from
      `usePortfolioSummary`) when the positions hook is empty.
    - Normalize ticker case on both sides of the join
      (`.toUpperCase().trim()`).
    - Map `incomeProjection.data?.positions ?? []` to contributors, filtering
      `annual_income > 0`.
    - Sort by `annualIncome` desc, take top 4.
    - Pass into builders with `totalAnnualIncome =
      incomeProjection.data?.total_projected_annual_income ?? 0` and
      `portfolioYieldOnValue` + `timestamp`.
    - Deps: `incomeProjection.data`, `positionsData?.holdings`,
      `data?.holdings`, `portfolioOverviewData?.summary.lastUpdated`.
  - Thread into `overviewArtifactBuilderContext`:
    ```ts
    incomeArtifact: overviewIncomeArtifact,
    ```
  - Add to memo dep array.
  - Add a new `case 'overview.income_projection':` to
    `renderOverviewArtifactEntry` (line 1591+). Structure: `NamedSectionBreak`
    label `"Income Projection"` + `GeneratedArtifact` when `entry.artifact`
    exists. No insight section above it — the directive annotation surfaces via
    `tags`, and lead/attention items already narrate income elsewhere.

- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.test.tsx`
  - Add `useIncomeProjection: vi.fn()` to the `@risk/connectors` mock (line 45
    block).
  - Add one new test: "renders income projection artifact when useIncomeProjection
    provides contributors and directive present". Assertions:
    - Card appears in POST bucket (after Market Context placeholder).
    - Claim text names the lead contributor.
    - Directive `annotation` appears as a tag.
  - Update existing tests that stub `useIncomeProjection` by returning
    `{ data: null, loading: false, error: null, refetch: vi.fn() }` — ensures
    the new hook call doesn't explode pre-existing scenarios.

## Out of scope

- 12-month timeline view (Option B deferred).
- Changing backend directive threshold (yield ≥ 2%).
- Adding warning badges to the income artifact.
- Changing the margin annotation anchor; once the card renders, it anchors
  naturally via the existing `ChatMargin` pathway.
- Changing the synthetic fallback data path in the resolver.

## Risks

1. **Weight map hydration.** Primary source is `positionsData?.holdings`, with
   `data?.holdings` fallback. If both are still loading when income data
   arrives, weight tags show `pending`; they become concrete as soon as either
   hook hydrates.
2. **Directive position collision in the POST bucket.** Other POST-bucket
   directives may emit positions around 40. Verify render order by inspection;
   adjust backend `position=40` if needed in a follow-up. Not a correctness bug.
3. **Shared ticks refactor breaks existing artifact visuals.** Moving
   `buildOverviewCurrencyTicks` out of the container is a pure extraction (no
   behavior change). Percent-tick helpers stay put. Risk limited to import-path
   bugs; covered by existing `overviewArtifactBrief.test.ts` + container test
   suite.
4. **Synthetic-mode silent suppression.** The artifact vanishes when the
   backend call fails — the user may expect to see it. Acceptable because we
   already don't fabricate per-ticker data; better to hide than to lie.

## Test plan

- `pnpm test overviewIncomeArtifactBrief` — new brief tests pass.
- `pnpm test artifacts/registry` — registry test fixture updated.
- `pnpm test PortfolioOverviewContainer` — existing tests green; new render
  test asserts card appears with directive + contributors.
- Manual QA: load overview with a dividend-bearing portfolio.
  - Card renders in POST-Market-Context section.
  - Claim names lead contributor.
  - Presets show income/yield/weight tags.
  - "Editorial: Income is material enough..." tag shows on the card.
  - Margin annotation appears spatially tied to the card (not orphaned).
  - Frontend warning log for `Unknown overview artifact directive ignored`
    no longer fires for `overview.income_projection`.

## Success criteria

- No frontend warning for `overview.income_projection` on briefs that include it.
- Income artifact card renders on the overview when income data is present.
- Directive `annotation` surfaces as the "Editorial" tag on the card.
- `changedFromPrevious` flag surfaces as the `ring-1 ring-primary/20` highlight
  when the directive reports it.
- Margin annotation anchors to a visible card instead of an orphan.
