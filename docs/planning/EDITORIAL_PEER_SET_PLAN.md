# Track C — Editorial Peer Set (Canonical Comps Framework)
*Resolver-only residual scope — storage + patch ops shipped in Track 0.*

**Status**: DRAFT R4 — addresses Codex R3 FAIL (0 blockers + 1 nit) — same-class wording fix in tests.
**Created**: 2026-05-07 (R0); revised 2026-05-07 (R1, R2, R3, R4).
**Revision history**:
- R4 — addresses Codex R3 FAIL: test case (j) carried the same ambiguous "non-empty editorial" wording R3 fixed in TC.D5; updated to "normalized, focal-filtered editorial result is non-empty" for consistency [P3].
- R3 — addresses Codex R2 FAIL: TC.D5 said "if editorial set is non-empty, auto-discovery is NOT consulted" — contradicted TC.D2/§6.2/test case (d) which fall through to auto-discovery when editorial set becomes empty after focal-filtering. R3 specifies "normalized, focal-filtered editorial set" as the gate condition [P3].
- R2 — addresses Codex R1 FAIL: removed leftover language asserting cross-repo `Thesis`/PYTHONPATH imports (audit-table row + TC.D1 rationale) that contradicted the Protocol-typed signature in TC.D2 [P2]; rewrote audit-table row about Track 0 apply-path enforcement to reflect the belt-and-suspenders read-side filter rather than the rejected "trust stored data" assumption [P3].
- R1 — addresses Codex R0 FAIL: (1) helper now owns the **full auto-discovery chain** (`get_subindustry_peers_from_ticker` → FMP `stock_peers` fallback) matching existing `compare_peers:360-417` behavior; helper does not regress to single-path lookup [P1]; (2) helper **filters focal ticker from editorial set** as belt-and-suspenders (Track 0 enforces on write but stale data + bypass paths could leak through) + dedupes + normalizes per `compare_peers:374` [P1]; (3) replaced runtime cross-repo `EditorialPeer` import with a local `Protocol` (`EditorialPeerLike` requiring just `.ticker: str`) — keeps risk_module tests runnable without AI-excel-addin schema on PYTHONPATH [P2]; (4) added test cases for focal filtering, ticker normalization (uppercase/strip), and dedupe parity [P2]; (5) simplified logging to module-level only on fallback events (matches existing `peers.py` pattern) — dropped per-resolution structured logging [P2]; (6) clarified subtitle that Track C is resolver-only residual scope [P3].
**Parent plan**: `docs/planning/CANONICAL_COMPS_FRAMEWORK_PLAN.md` R6 (Codex PASS) — see §6 for Track C scope.
**Prerequisite**: Track 0 (`SCHEMA_AND_PATCH_OPS_PLAN.md` R4 PASS) — SHIPPED on AI-excel-addin commit `7ce654d`.
**Closes**: prerequisite for Tracks A and B's peer-set inputs.

**Authoritative code references** (verified by file read 2026-05-07):
- `AI-excel-addin/schema/thesis_shared_slice.py` — `EditorialPeer` (new in Track 0), `IndustryAnalysis.editorial_peer_set` (new in Track 0)
- `AI-excel-addin/schema/handoff_patch.py` — `AddEditorialPeerOp`, `RemoveEditorialPeerOp`, `SetEditorialPeerSetOp` (new in Track 0)
- `risk_module/fmp/tools/peers.py:360-417` — `compare_peers` peer-list resolution; `peer_list = [t for t in peer_list if t != symbol]` at L417 (the focal-exclusion convention Track C inherits)
- `risk_module/core/proxy_builder.py` — `get_subindustry_peers_from_ticker` (auto-discovery fallback)

---

## 1. Purpose

Ship the **override-rule helper** that Tracks A and B both call to resolve a thesis's peer universe: editorial set wins, auto-discovery falls back. The framework plan §6 defines the rule; Track C is the single shared implementation.

This plan does **not** ship the editorial peer-curation skill (downstream, separate plan). It does **not** ship CLI/MCP user-facing surfaces (deferred follow-up). Track 0 already shipped storage, patch ops, and apply-path focal-ticker enforcement.

---

## 2. Audit findings (grounded by code read)

| Finding | File / location | Implication |
|---|---|---|
| `compare_peers` already excludes focal at `peer_list = [t for t in peer_list if t != symbol]` | `fmp/tools/peers.py:417` | Track C helper inherits this convention; editorial set is "peers only" (no focal); helper enforces focal-exclusion as belt-and-suspenders (Track 0 enforces on write paths) |
| `compare_peers` auto-discovery is a **two-step chain**: `get_subindustry_peers_from_ticker` → on `SubindustryPeerGenerationError` or empty result → FMP `stock_peers` endpoint | `fmp/tools/peers.py:367-405` | Helper must own the full chain; framework §6 named only step 1 but existing code does both. Single-step helper would regress |
| `compare_peers` dedupes peer list with `peer_list = list(dict.fromkeys(peer_list))` after subindustry call | `fmp/tools/peers.py:374` | Helper must dedupe both editorial and auto-discovery results to match existing semantic |
| Editorial peer entries via cross-repo Pydantic import would require `schema` package on PYTHONPATH; not currently set up in this repo | `importlib.util.find_spec("schema") -> None` | Helper uses local `Protocol` (`EditorialPeerLike` with `.ticker: str`) — no runtime cross-repo import; AI-excel-addin's `EditorialPeer` satisfies the Protocol structurally |
| `EditorialPeer` model + `editorial_peer_set` field + 3 patch ops shipped in Track 0 | AI-excel-addin commit `7ce654d` | Storage and write surfaces exist; Track C is read-side only |
| Apply-path focal enforcement (rejects EditorialPeer where ticker == focal) shipped in Track 0 | `AI-excel-addin/api/research/patch_engine.py` (Track 0 modified) | Track 0 enforces on write; helper still applies belt-and-suspenders focal filtering at read time (per TC.D2) — guards against stale data + bypass paths (direct DB writes, migrations, etc.) |
| Framework §6 override rule: "if `editorial_peer_set` is non-empty, downstream tools use it verbatim; otherwise fall back to FMP auto-discovery" | framework R6 §6 | Helper signature + behavior locked |
| Helper has **no runtime cross-repo dependency** — takes `focal_ticker: str` + `editorial_peer_set: Sequence[EditorialPeerLike]` (per TC.D2). Callers extract these fields from a Thesis at call time. | (this repo) | Helper lives in **risk_module** — that's where the consumers (Tracks A/B in risk_module) are. No `Thesis` import; no `EditorialPeer` import; only a local `Protocol` (`EditorialPeerLike`) |

**Gap summary:** Track 0 shipped everything needed except the resolver function itself. The override rule lives in framework §6 prose only — no executable contract yet. Track C ships exactly that.

---

## 3. Locked design decisions

### TC.D1. Helper lives in risk_module
`risk_module/utils/peer_resolver.py` (new module). Rationale: Tracks A and B (the callers) live in risk_module — putting the helper there matches the consumer side. Helper has **no runtime cross-repo import** (per TC.D2 Protocol typing); callers extract `focal_ticker` and `editorial_peer_set` from a Thesis at call time and pass them directly. Putting the helper in AI-excel-addin would force Tracks A/B to import a non-data-side helper from a different repo — wrong direction.

### TC.D2. Helper signature: pure function, Protocol typing, full auto chain, normalization
```python
from typing import Literal, Protocol, Sequence

class EditorialPeerLike(Protocol):
    """Structural type for editorial peer entries.
    AI-excel-addin's EditorialPeer (Pydantic) satisfies this via duck-typing
    without requiring a runtime cross-repo import."""
    ticker: str

def resolve_peer_universe(
    focal_ticker: str,
    editorial_peer_set: Sequence[EditorialPeerLike] | None,
    *,
    fmp_client: Any | None = None,  # injected for tests; defaults to FMPClient()
) -> tuple[list[str], Literal["editorial", "auto"]]:
    """Returns (peer_tickers_excluding_focal, source).

    Behavior:
    - Normalizes focal: strip + uppercase
    - If editorial_peer_set is non-empty:
        - Normalizes each peer ticker (strip + uppercase)
        - Filters focal (belt-and-suspenders; Track 0 enforces on write)
        - Dedupes preserving order (matches compare_peers:374)
        - If non-empty after filtering: returns (peers, 'editorial')
        - If empty after filtering: falls through to auto-discovery
    - Auto-discovery chain (matches compare_peers:367-405):
        1. get_subindustry_peers_from_ticker(focal); dedupe
        2. On SubindustryPeerGenerationError or empty: FMP stock_peers fallback
        3. On both empty/failed: raise PeerResolutionError
    - Auto results: filter focal + dedupe + return (peers, 'auto')
    """
```

Caller passes `focal_ticker` and `editorial_peer_set` directly — helper does **not** take a Thesis object. Rationale: keeps the helper testable without Thesis fixtures, avoids cross-repo Thesis-construction in tests, and isolates the override rule from Thesis-shape changes.

`fmp_client` injection parameter exists purely for testability (mock-injectable). Production callers omit it; helper instantiates `FMPClient()` once when needed.

### TC.D3. Source field on the return value (`"editorial" | "auto"`)
Track A and B need to surface "where the peer set came from" in their artifacts (for transparency / debugging). Returning the source as part of the tuple is cheaper than re-deriving downstream. Not a Pydantic-level change in Track 0 — purely a helper return-type concern.

### TC.D4. Empty editorial set treated as "absent"
If `editorial_peer_set is None` OR `editorial_peer_set == []`, fall back to auto-discovery. Matches framework §6 "absent or empty, fall back" wording exactly.

### TC.D5. No silent merging — pure either/or
If the **normalized, focal-filtered** editorial set is non-empty, auto-discovery is NOT consulted (matches framework §6 "explicit-wins-or-falls-back"). If editorial input is `None`, `[]`, or becomes empty after normalization + focal-exclusion (e.g., editorial set contained only the focal ticker), the helper falls through to auto-discovery. No "editorial peers + auto-fill remaining" semantic. Simpler contract, easier to reason about.

### TC.D6. No new patch ops or storage in Track C
Track 0 shipped `AddEditorialPeerOp` / `RemoveEditorialPeerOp` / `SetEditorialPeerSetOp`. Track C consumes them by reading state, doesn't add new write paths. CLI/MCP/skill surfaces that invoke those ops are downstream / deferred.

### TC.D7. New exception type for both-sources-empty case
```python
class PeerResolutionError(Exception):
    """Raised when neither editorial set, subindustry classifier, nor FMP
    stock_peers yields any peers. Caller decides surface (HTTP 4xx, MCP error,
    fail-loud per project pattern, etc.)."""
```

Lives in `peer_resolver.py` alongside the helper. Matches existing project "fail loudly" convention (see e.g. `core.action_errors.IndustryToolUpstreamError` for the pattern). Distinct from `SubindustryPeerGenerationError` which is auto-step-1-specific.

---

## 4. File-by-file changes

### risk_module (primary)

**New module**: `risk_module/utils/peer_resolver.py`
- Defines local `EditorialPeerLike` Protocol (TC.D2) — no cross-repo import
- Exports `resolve_peer_universe(focal_ticker, editorial_peer_set, *, fmp_client=None)` per TC.D2
- Exports `PeerResolutionError` per TC.D7
- Imports `get_subindustry_peers_from_ticker` + `SubindustryPeerGenerationError` from `core.proxy_builder`
- Imports `FMPClient` from `fmp.client` for stock_peers fallback (matches `compare_peers:358`)
- Internal helper to parse FMP stock_peers response (the same dispatch logic at `fmp/tools/peers.py:393-404` covering old `peersList` shape and new `[{symbol}]` shape) — extract into a private `_parse_stock_peers_response(payload)` so both `compare_peers` (in a future Track A integration) and the helper can share it
- Logging: minimal — `portfolio_logger.warning` only on auto-discovery fallback events (subindustry → FMP, or both empty). No per-resolution logging.

**No changes** to:
- `fmp/tools/peers.py` — Track A's plan integrates the helper into `compare_peers` (or a wrapper); Track C just ships the helper
- `mcp_tools/industry.py` — Track A's plan handles the dual-write integration
- Any AI-excel-addin file — Track 0 already shipped everything needed there

### AI-excel-addin
No changes. (Track 0 already shipped storage, patch ops, apply-path enforcement.)

---

## 5. Tests

| Test file | Coverage |
|---|---|
| `risk_module/tests/utils/test_peer_resolver.py` (new) | Test cases: (a) editorial set non-empty → returns its tickers + "editorial"; (b) editorial set None → auto-discovery + "auto"; (c) editorial set [] → auto-discovery + "auto"; (d) editorial set with **only focal** ticker → falls through to auto-discovery (post-filter empty); (e) editorial set with focal + peers → focal filtered, remaining peers returned + "editorial"; (f) editorial set with **lowercase / whitespace** tickers → normalized to uppercase + stripped (parity with `compare_peers:363`); (g) editorial set with **duplicate tickers** → deduped preserving first occurrence (parity with `compare_peers:374`); (h) editorial set values preserved in order after normalization/filter/dedupe; (i) helper does NOT mutate input; (j) helper does NOT call auto-discovery when the normalized, focal-filtered editorial result is non-empty (verify via mock); (k) auto-discovery raises `SubindustryPeerGenerationError` → falls back to FMP `stock_peers` (verify via mock); (l) FMP `stock_peers` returns old `peersList` shape → parsed correctly; (m) FMP `stock_peers` returns new `[{symbol}]` shape → parsed correctly; (n) both subindustry empty and FMP `stock_peers` fail/empty → raises `PeerResolutionError`; (o) auto-discovery result containing focal → focal filtered. |

~14-15 test cases. One file, no integration tests needed — the helper is pure and the upstream/downstream surfaces are tested in their own tracks.

---

## 6. Cross-cutting concerns

### 6.1 Logging
**Minimal** — match existing `peers.py` pattern (which uses module-level `logger.warning` only on failure paths, not on each successful resolution). Helper emits:
- `logger.warning(...)` if subindustry fails or returns empty AND helper falls back to FMP `stock_peers` (matches `peers.py:376-381` log statement)
- `logger.warning(...)` if FMP `stock_peers` also fails or returns empty (just before raising `PeerResolutionError`)
- No per-resolution structured logging — that's consumer-side concern (callers can wrap and log if needed)

### 6.2 Error handling
- `SubindustryPeerGenerationError` from auto-discovery is **caught internally** and triggers FMP `stock_peers` fallback (per TC.D2 chain semantics)
- `PeerResolutionError` (new — TC.D7) raised when both subindustry and FMP `stock_peers` yield empty/fail. Caller decides surface (HTTP 4xx, MCP error, etc.).
- Empty editorial set is NOT an error — falls through to auto-discovery
- Editorial set containing only focal ticker (post-filter empty) is NOT an error — falls through to auto-discovery (per test case "d")

### 6.3 No caching
Helper is cheap (list-or-fallback). Caching lives one layer up in `compare_peers` (15-min TTL on `_peer_metric_snapshot_cache`). Track C does not introduce additional caching.

---

## 7. Out of scope

- **Editorial peer-curation skill** — downstream, separate plan (per framework §6 "skill interface")
- **CLI / MCP user-facing surfaces** for editorial peer CRUD — deferred follow-up; Track 0's patch ops + existing API patch endpoints already support programmatic CRUD
- **`compare_peers` integration** — Track A's plan wires the helper into the existing `compare_peers` peer-resolution path (currently at `fmp/tools/peers.py:360-417`)
- **Operating-comps integration** — Track B's plan wires the helper into the operating-comps build pipeline
- **Historical peer-set rollback / revisioning** — Thesis CAS already audits via Track 0 patch ops; no new revisioning concern
- **Per-industry peer registry (v2)** — explicitly v2 per framework D5
- **Dual-source merge semantics** — explicitly rejected per TC.D5

---

## 8. Rollout sequence

Single phase. Helper has no behavioral effect until Tracks A and B integrate it (each in their own follow-on plan):
1. Ship `peer_resolver.py` + tests on a feature branch (or directly to main per project's commit-on-main default)
2. Track A's impl plan integrates the helper into `compare_peers` / `industry_peer_comparison`
3. Track B's impl plan integrates the helper into the operating-comps builder

Track C ships independently of the feature flag (`INDUSTRY_ANALYSIS_V1_2_ENABLED`). The helper is callable any time; consumers (A/B) gate their own writes behind the flag per Track 0.

---

## 9. Open questions (deferrable to consumer tracks)

1. **`compare_peers` integration shape**: should the helper be called inside `compare_peers` itself (so all callers benefit) or outside it by `industry_peer_comparison` (keeping `compare_peers` agnostic)? Decided in Track A impl plan. Either path is compatible with Track C's helper signature.
2. **Logging granularity**: include rationale strings from `EditorialPeer` entries in the log line, or just tickers? Decided in Track A impl plan based on what observability surfaces want.
3. **Fallback when both editorial AND auto-discovery fail**: helper raises (current default — matches existing `compare_peers` behavior). Should Track A surface a more user-friendly error? Decided in Track A.

---

## 10. Summary

Track C is **resolver-only residual scope** — Track 0 absorbed the schema + patch-op + apply-path work. What remains is **one shared resolver function** that encodes the override rule from framework §6 AND the existing two-step auto-discovery chain from `compare_peers`:

- **1 new module** (`risk_module/utils/peer_resolver.py`)
- **1 pure function** with Protocol typing, full auto-discovery chain, normalization (`resolve_peer_universe`)
- **1 new exception type** (`PeerResolutionError` — both-sources-empty case)
- **1 local Protocol** (`EditorialPeerLike` — no runtime cross-repo import)
- **1 test file** (~14-15 cases covering normalization, focal filtering, fallback chain, both-source-shapes parsing)
- **0 schema changes, 0 patch ops, 0 cross-repo edits**

After Track C ships, Tracks A and B each integrate the helper at their own plans — Track A wires it into `compare_peers` / `industry_peer_comparison`; Track B wires it into the operating-comps builder. Both tracks unblocked at Track C merge.

---
