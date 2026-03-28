# Security Identity Canonicalization Plan

## Status

Draft

## Context

The "zero factor betas" issue is not primarily a factor-regression math problem. It is a security-identity problem that is later masked as a risk output problem.

Today, the same instrument can appear under multiple symbols depending on which part of the pipeline is using it:

- raw/source symbol from the portfolio feed, for example `AT.`
- stripped or normalized portfolio symbol, for example `AT`
- provider lookup symbol, for example `AT.L`

This creates inconsistent behavior across the analysis pipeline:

- some paths resolve aliases before building proxies
- some paths perform direct symbol lookups against caches
- some paths refresh proxies before analysis
- some paths trust persisted proxy snapshots as-is

When one of those paths misses, the instrument is excluded from factor-model coverage. Downstream, missing betas are filled to `0.0` for internal math, and the filled values are exposed broadly enough that "not modeled" is easy to misread as "true zero beta."

The current bug around `AT.` is one concrete example, but the problem is architectural and will recur for any symbol that needs normalization, alias resolution, venue mapping, or identifier-based matching.

## Goal

Create a single, explicit security-identity model for the portfolio and risk pipeline so that:

- one instrument has one internal identity within a portfolio analysis
- provider symbol translation happens only at provider boundaries
- caches and analysis maps do not depend on ad hoc raw ticker strings
- missing model coverage remains distinguishable from zero exposure

## Non-Goals

This plan does not require:

- changing the factor regression methodology
- rewriting every provider integration in one pass
- immediately replacing all symbol-based logic with identifier-only logic
- changing user-visible portfolio symbols unless needed for correctness

## Proposed Model

Introduce a first-class `SecurityIdentity` object and use it as the canonical join contract across the analysis pipeline.

Suggested fields:

- `security_key`: stable internal key used for joins, caches, and analysis maps
- `source_symbol`: raw incoming symbol from the portfolio source, for example `AT.`
- `portfolio_symbol`: normalized internal/display symbol, for example `AT`
- `data_symbol`: provider lookup symbol, for example `AT.L`
- `instrument_type`: equity, ETF, ADR, mutual fund, cash-equivalent, option, etc.
- `security_identifiers`: optional ISIN / CUSIP / FIGI / other identifiers when available
- `exchange` or `venue`: optional but important when symbol collisions exist
- `currency`: optional disambiguation and validation field

### Keying Rule

The long-term target is identifier-backed identity first, symbol-backed identity only as fallback.

Practical phased rule:

- if durable identifiers are available and trusted, derive `security_key` from those identifiers
- otherwise derive `security_key` from normalized symbol plus the minimum disambiguators needed for uniqueness, typically venue and instrument type

The exact shape of `security_key` is less important than enforcing that it is:

- stable within the system
- generated once per ingested holding
- reused everywhere downstream

## Architectural Rules

### 1. Resolve Once, Early

Security identity should be resolved as part of position ingestion or portfolio snapshot construction, not lazily and repeatedly in downstream services.

That means:

- parse the raw holding
- normalize the incoming symbol
- resolve alias/provider mapping
- assign canonical identity fields
- persist both raw and canonical forms

### 2. Separate Identity From Provider Lookup

Ticker strings should no longer serve double duty as both:

- the internal identity of the holding
- the symbol sent to an external provider

Only provider adapters should care about `data_symbol`. Internal analysis code should operate on `security_key` and identity-bearing portfolio objects.

### 3. Key All Analysis State Off Canonical Identity

The following should eventually be keyed by `security_key` rather than arbitrary symbol strings:

- `PositionsData` / `PortfolioData`
- factor proxies
- security type caches
- asset-class classification caches
- expected return inputs
- risk result per-security maps
- diagnostics and coverage metadata

### 4. Preserve Missing vs Zero Semantics

Internal matrix math may still require filled zeros in some places. That is acceptable as an implementation detail.

However, the externally visible data model must preserve whether a security was:

- modeled successfully
- excluded because no proxy was found
- excluded because classification failed
- excluded because history was insufficient
- intentionally assigned zero exposure

The system should not collapse those states into a single `0.0` output.

## Target Data Flow

### Ingestion / Snapshot Build

1. Read raw holding from source.
2. Build `SecurityIdentity`.
3. Persist raw symbol and canonical identity fields together.
4. Emit `PortfolioData` keyed by `security_key`.

### Classification / Proxy Generation

1. Use canonical identity as the join key.
2. Resolve provider-specific `data_symbol` only inside the provider adapter or resolver boundary.
3. Store resulting classifications and proxies against canonical identity.

### Risk Analysis

1. Read factor proxies keyed by canonical identity.
2. Compute raw per-security exposures.
3. Preserve raw nullable/missing state for diagnostics and API serialization.
4. Apply any zero-filling only in internal aggregation layers that mathematically require it.

## Storage and Interface Changes

### Portfolio Holdings

Holdings and snapshots should carry both raw and resolved identity fields:

- raw source symbol for traceability
- canonical `security_key`
- normalized `portfolio_symbol`
- provider `data_symbol`

This allows debugging without reintroducing ambiguity into joins.

### Cached Tables / Snapshots

Caches such as factor proxies and security classifications should be keyed by canonical identity, not by whichever ticker string happened to be present when the row was first created.

This likely requires:

- schema changes or stored-record shape changes
- cache versioning
- migration or invalidation of old rows

### Risk Result Objects

Risk outputs should expose:

- raw betas or exposures with nullable values
- coverage or modeling status per security
- filled values only where explicitly labeled as calculation-only outputs

## Incremental Rollout Plan

### Phase 0: Define the Identity Contract

- introduce `SecurityIdentity` and helper/resolver interfaces
- document canonicalization rules
- define `security_key` generation strategy
- identify current entry points that create holdings and portfolio snapshots

Exit criteria:

- one shared identity contract exists
- canonicalization logic has one home
- no new code paths add ad hoc symbol normalization

### Phase 1: Thread Identity Through Portfolio State

- update portfolio ingestion / snapshot-building code to attach canonical identity
- update `PositionsData` / `PortfolioData` to carry canonical fields
- keep legacy symbol fields temporarily for compatibility

Exit criteria:

- downstream consumers can access canonical identity without recomputing it
- one portfolio analysis run has a single canonical key per security

### Phase 2: Move Classification and Proxy Generation to Canonical Keys

- update factor proxy generation to read/write canonical identity
- update `SecurityTypeService` and asset-class lookup paths to use the shared resolver
- remove direct alias-map lookups from downstream classification code

Exit criteria:

- proxy generation and classification resolve the same instrument the same way
- `AT.` / `AT` / `AT.L` all converge to one canonical security in the pipeline

### Phase 3: Fix Output Semantics

- preserve raw nullable betas/exposures
- add explicit modeling or coverage status to result objects
- keep internal fill-to-zero logic only where required for aggregation math

Exit criteria:

- API and diagnostics can distinguish missing coverage from real zero exposure
- UI or debugging consumers do not need to infer coverage from zeros

### Phase 4: Migrate and Backfill Cached Data

- invalidate or version old proxy/classification caches
- backfill canonical identity into persisted records where feasible
- rebuild affected snapshots and derived data

Exit criteria:

- stale pre-canonicalization cache rows are no longer silently reused
- canonical and legacy records do not compete for the same security

### Phase 5: Remove Legacy Symbol-Based Joins

- remove fallback join logic based on raw ticker strings
- eliminate duplicate symbol-normalization helpers outside the shared resolver
- tighten invariants and assertions around canonical identity usage

Exit criteria:

- analysis no longer depends on symbol-string coincidence
- new bugs of the `AT.` class become structurally harder to introduce

## Minimal First Implementation Slice

The full architecture should be rolled out incrementally. The first implementation slice should reduce user-facing risk while aligning with the target design.

Recommended first slice:

- centralize alias resolution behind one resolver entry point
- replace direct `ticker_alias_map.get(...)` style logic in classification paths with the shared resolver
- ensure factor proxy generation and security-type lookup use the same resolved lookup symbol
- expose missing coverage distinctly from zero in risk outputs or diagnostics

This first slice does not fully solve identity architecture, but it stops the most immediate inconsistency while enabling the broader migration.

## Migration Considerations

### Cache Invalidation

Persisted factor proxies and classifications created under legacy symbol rules should not be trusted indefinitely once canonical identity is introduced.

Migration options:

- hard invalidate and rebuild all affected caches
- version cache records and read only canonicalized versions
- run targeted backfills for portfolios known to contain alias-sensitive holdings

### Duplicate Historical Records

The same instrument may already exist under multiple symbols in persisted data. Migration needs a deduplication strategy so that:

- `AT.`
- `AT`
- `AT.L`

do not survive as competing records for the same security after canonicalization.

### Compatibility Window

For a transition period, result objects and internal models may need to carry both:

- legacy symbol-indexed fields
- canonical identity-indexed fields

This should be treated as temporary compatibility scaffolding, not a permanent dual model.

## Test Plan

Add end-to-end coverage around alias-sensitive instruments and missing-coverage semantics.

Required scenarios:

- portfolio contains `AT.` and resolves to the same canonical identity used by proxy generation
- classification and asset-class lookup choose the same provider symbol for that security
- factor proxies, risk analysis, and result serialization all use the same canonical key
- an unmodeled security remains explicitly unmodeled in diagnostics or API output, rather than appearing as a true zero-beta holding
- persisted stale proxy/classification rows do not override canonicalized fresh data

At minimum, tests should exercise:

- identity resolution
- portfolio snapshot construction
- proxy generation
- security type classification
- asset-class lookup
- risk result serialization

## Open Questions

- Should `security_key` be identifier-first immediately, or should the first rollout use normalized symbol plus venue as an intermediate step?
- Which fields are guaranteed to be available at ingestion time for all portfolio sources?
- How should UI layers choose between `source_symbol`, `portfolio_symbol`, and `data_symbol` for display?
- How much legacy persisted data is worth backfilling versus invalidating?
- Are there any existing APIs that depend on zeros instead of nullable/missing coverage states?

## Acceptance Criteria

This effort is complete when all of the following are true:

- the same instrument does not appear under multiple internal keys during one analysis
- provider lookups use `data_symbol`, not raw portfolio ticker strings
- factor proxies and classifications agree on security identity
- risk outputs distinguish missing coverage from real zero exposure
- stale legacy symbol-based cache rows no longer silently control analysis results

## Immediate Next Step

Before implementation begins, convert this plan into a concrete work breakdown with:

- schema or model changes
- ownership of each affected module
- migration order
- test additions
- rollout and fallback strategy

That work breakdown should be small enough to execute in stages without requiring a risky all-at-once rewrite.
