# Account + Institution Filtering Plan (v3)

## Status
- Implementation changes were reverted.
- This plan is implementation-gated: no code changes until each gate below is verified.

## Why prior attempt failed
- Resolver split IBKR into separate logical accounts in live shape:
  - positions side: SnapTrade UUID/display name
  - transactions side: IBKR native U-account
- Test fixture incorrectly bridged those identities via transaction account_name, which is often empty in live IBKR flex data.
- Result: alias-equivalence passed in tests but failed in live runs.

## Objectives
1. Same logical account must resolve identically for all aliases.
2. Resolver behavior must match live IBKR row shape.
3. Preserve provider-flow dedup/authority identity semantics.
4. Keep scope limited to realized account/institution filtering.

## Gate 0: Live shape contract capture (required before design)
Deliverables:
- Snapshot fixture for IBKR realized path containing:
  - position rows (account_id, account_name, brokerage/institution, position_source)
  - normalized FIFO txn rows (account_id, account_name, institution)
  - provider metadata rows (account_id/account_name/provider/institution)
- Explicit marker of placeholder tokens (for example `-`, empty strings).

Pass criteria:
- Fixture demonstrates current production mismatch shape (UUID/display-name vs U-account).
- Fixture is saved under tests fixtures for deterministic replay.

## Gate 1: Resolver spec update (design only)
Define deterministic linking rules and disallowed links.

Required rules:
1. Token normalization is centralized and reused everywhere.
2. Placeholder account tokens are excluded from candidate creation (`-`, empty, `unknown`).
3. Strong-link rules:
- explicit ID token equality
- explicit provider metadata ID mapping
- explicit account_name equality only when name is account-specific (not generic labels)
4. Singleton bridge rule (strictly bounded):
- allowed only when institution+source scope contains exactly one viable position-account candidate and exactly one viable transaction-account candidate
- if more than one on either side -> ambiguous (no auto-link)
5. Ambiguous and not-found always return structured error payload.

Pass criteria:
- Written rule table with positive and negative examples from the live fixture.

## Gate 2: Test-first matrix (must fail on current code)
Add tests before implementation:
1. Live-shape IBKR alias equivalence fixture:
- txn account_name empty
- positions UUID/display name
- metadata includes U-account and placeholder row
2. All aliases (`U2471778`, display name, UUID) resolve to one canonical account.
3. Structured error propagation survives core -> service -> MCP unchanged.
4. Provider-flow dedup/authority key invariance:
- alias filtering changes inclusion only
- raw dedup/authority identity keys remain unchanged.
5. Multi-account ambiguity case returns `ambiguous` (no singleton bridge).

Pass criteria:
- New tests fail on reverted baseline for the expected reasons.

## Gate 3: Implementation scope
Only after Gates 0-2 pass.

Implementation steps:
1. Resolver update with rules above.
2. Run resolver before analyzer account filtering.
3. Keep analyzer preload unfiltered by raw account token in realized path.
4. Apply alias-set matching consistently to holdings/txns/provider-flow/futures MTM.
5. Add `realized_metadata.account_resolution` always (bypassed when account omitted).
6. Preserve raw provider identity keys for dedup/authority.

## Gate 4: Validation
Required checks:
1. Targeted test suite passes.
2. Live alias matrix passes:
- `U2471778`, display name, UUID produce identical realized outputs.
3. Account resolution diagnostics show one canonical account for all three aliases.
4. No reintroduction of deferral logic.

## Gate 5: Incident metric re-check
After filter fix is validated:
- Recompute broker delta for IBKR baseline period.
- If delta remains large, open separate plan for PnL/flow fidelity (not account filtering).

