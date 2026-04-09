# F16 v9.7 — CSV Import Collision Guard (Slim Plan)

## Context

When a user CSV-imports positions for an institution that already has an active API connection (Plaid, SnapTrade, Schwab, IBKR), duplicate positions silently appear in `CURRENT_PORTFOLIO`. There is no cross-source collision detection. This plan adds collision detection at CSV import time, blocks the import unless the user explicitly forces, and surfaces the warning + force-retry path in the frontend.

The fix needs a trustworthy "is this institution actively connected via API?" signal. The natural signal — `data_sources.status` — was a ghost column until **F17 shipped (commit `53265062`)**. F17 wired `status` through the entire brokerage lifecycle: upsert guard, deactivation in 5 disconnect/delete/recovery paths, status-aware registry queries, sync reconciliation, admin cleanup script. F16 v9 builds on top of that signal.

This plan is the v9 reframe of `docs/planning/CSV_IMPORT_COLLISION_GUARD_PLAN_TABLED.md` (v8, 8 Codex review rounds). **Step 0 of the tabled plan is now obsolete** — F17 already shipped all the disconnect/deactivation work and 9 of the tabled plan's 23 tests. This plan covers only the remaining work: collision detection in `import_portfolio`, MCP wrapper, web routes, frontend UI, and 15 net-new tests.

## Codex Review History

**v9 → FAIL (5):** (1) `collision_blocked` added to wrong frontend type — `CsvPreviewResponse` is preview-only; need to widen `CsvImportCompletionResponse` and `CsvImportFullResponse`, plan must include `useOnboardingActivation.ts`. (2) Race-window UX of "toast and re-preview" not implementable — Wizard/Landing state machines transition to processing→done and retry re-submits the stale selection. (3) Real-import collision lookup runs before validation guard despite plan claiming validation-first ordering. (4) Missing `force=true` test for `/import-csv-full`. (5) Collision payload doesn't dedupe/sort when registry has multiple active rows for same `(provider, institution_slug)`.

**v9.1 → FAIL (4):** (1) Dedupe key still wrong — used `(provider, display_name)` instead of `(provider, institution_slug)` (the registry's actual ambiguity key). (2) Dry-run "complete picture" claim unbacked — Phase 3 doesn't forward `errors`/`can_import` and `CsvImportStep` doesn't gate confirm on validation. (3) Existing exact-match test `test_onboarding.py:1333` would break from adding `"collision": null` to preview response. (4) Settings race-recovery description wrong — `requestPreview` only fires on file/institution change, not on re-clicking Import.

**v9.2 → FAIL (4):** (1) `requestPreview()` call graph claim too narrow — also fires from normalizer activation (`CsvImportStep.tsx:191`) and "Select institution manually" path (`CsvImportStep.tsx:329`). (2) "Re-select the same file" recovery is unreliable — HTML file inputs typically don't fire onChange when the same file is re-picked because the input value isn't reset. (3) `EmptyPortfolioLanding` recovery via `onSkipForNow` wrong — that handler only writes localStorage; the actual restart path is the persistent "Import a CSV" button at `EmptyPortfolioLanding.tsx:160`. (4) Validation-order rationale ambiguous — the collision *lookup* runs before the validation guard at line 311, but the *return branch* (collision_blocked) runs after; plan conflated lookup and return.

**v9.3 → FAIL (1):** Stale Open Question #4 still asked whether dry-run `collision` should be "always present (`null` or dict)" — contradicts the v9.2/v9.3 contract that the key is omitted when null to preserve the exact-match test at `test_onboarding.py:1333`.

**v9.4 → FAIL (2):** Two stale text items carried over from the original v9 draft that I never touched: (1) Out-of-Scope item #2 still listed Plaid `provider_items` cleanup on full delete as a gap, but F17 already wired that cleanup at `routes/plaid.py:1738` (covered by `tests/routes/test_plaid_disconnect.py:115`). (2) Risks item #4 described `CsvImportCard` as having an `uploadCsv` helper, but it actually posts directly inside `handleConfirm` at `CsvImportCard.tsx:33` — only `OnboardingWizard` and `EmptyPortfolioLanding` have a separate `uploadCsv` helper.

**v9.5 → FAIL (2):** Two minor line-number citation drifts: (1) `import_transactions.py:267` → actual line is `mcp_tools/import_transactions.py:270`. (2) MCP wrapper call "at line 436" → actual line 437.

**v9.6 → FAIL (1):** Verification step 6 claimed settings frontend would see `collision_override=True`, but `/import-csv-full` route builds its own success payload at `routes/onboarding.py:825` and does NOT forward that field. Observable only via MCP (steps 4-5).

All findings addressed in v9.7 below.

## Critical Design Decision: HTTP 200 with status discriminator (NOT 409)

`frontend/packages/app-platform/src/http/HttpClient.ts:78-136` rejects any non-2xx response with a thrown `RetryableHttpError` whose only payload is `status` and `statusText`. The JSON body is parsed only on `response.ok === true` (line 42, line 89). The single special case is 403 with `detail.error === "upgrade_required"` (line 106-111, 217-238). Nothing else parses bodies on error.

If routes return HTTP 409 for collisions, the frontend has zero access to the `collision` dict and cannot offer a force-retry path.

**Decision**: routes return HTTP **200** with an in-body `status: "collision_blocked"` discriminator. This matches how `status: "needs_normalizer"` already works (`CsvImportStep.tsx:112`). No HttpClient changes required. This is the single biggest delta vs the tabled v8 plan, which prescribed 409.

## Files to Modify

| File | Change |
|------|--------|
| `mcp_tools/import_portfolio.py` | Add `_check_api_collision()` helper (with dedupe + sort), `force` param, dry-run collision field, real-import collision branch (placed AFTER validation guard) |
| `mcp_server.py` | Add `force: bool = False` to MCP wrapper (line 426), pass through |
| `routes/onboarding.py` | Forward `collision` from preview, accept `force` form field on `/import-csv` and `/import-csv-full`, surface `collision_blocked` via `_shape_csv_error` |
| `frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx` | Add `collision` field to `CsvPreviewResponse`, extend `CsvImportSelection` with `force?: boolean`, render collision banner with acknowledgment checkbox, thread `force` into `onConfirm` |
| `frontend/packages/ui/src/components/onboarding/useOnboardingActivation.ts` | Widen `CsvImportCompletionResponse.status` union to include `'collision_blocked'`, add `collision` field. Existing error path at lines 241-248 already routes the message to the error completion screen — no behavior change required. |
| `frontend/packages/ui/src/components/onboarding/OnboardingWizard.tsx` | Append `force` to FormData when `selection.force === true` |
| `frontend/packages/ui/src/components/onboarding/EmptyPortfolioLanding.tsx` | Same as OnboardingWizard |
| `frontend/packages/ui/src/components/settings/CsvImportCard.tsx` | Append `force` to FormData; widen local `CsvImportFullResponse.status` union to include `'collision_blocked'`, add `collision` field. Existing toast path at lines 80-86 surfaces the message — no behavior change required. |
| `tests/mcp_tools/test_import_portfolio.py` | 9 collision tests |
| `tests/routes/test_onboarding_csv_collision.py` (new) | 6 route-level tests |
| `frontend/packages/ui/src/components/onboarding/__tests__/CsvImportStep.collision.test.tsx` (new, optional) | 4 frontend tests |

## Implementation

### Phase 1 — Backend collision detection

**`mcp_tools/import_portfolio.py`**

Add import:
```python
from providers.routing import normalize_institution_slug, POSITION_PROVIDERS
```

Add helper after line 71 (before `_load_lines`):
```python
def _check_api_collision(institution_slug: str, user_email: str) -> list[dict[str, Any]] | None:
    """Return active API data_sources colliding with this institution, or None.

    Best-effort: returns None if DB unavailable, user not found, or query fails.
    Dedupes by (provider, institution_slug) — the same identity the registry treats
    as ambiguous (services/account_registry.py:209) — and sorts deterministically
    so the same input always renders the same UI ordering.
    """
    if not is_db_available():
        return None
    try:
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
            user_row = cursor.fetchone()
            if not user_row:
                return None
            # DISTINCT ON collapses (provider, institution_slug) duplicates and picks
            # the first non-null institution_display_name for the pair via ORDER BY ...
            # NULLS LAST. Postgres requires the DISTINCT ON expressions to lead the
            # ORDER BY, hence the (provider, institution_slug) prefix.
            cursor.execute(
                """
                SELECT DISTINCT ON (provider, institution_slug)
                    provider,
                    institution_slug,
                    institution_display_name
                FROM data_sources
                WHERE user_id = %s
                  AND institution_slug = %s
                  AND provider = ANY(%s)
                  AND status = 'active'
                ORDER BY provider, institution_slug, institution_display_name NULLS LAST
                """,
                (user_row["id"], institution_slug, list(POSITION_PROVIDERS)),
            )
            rows = cursor.fetchall()
            if not rows:
                return None
            return [dict(r) for r in rows]
    except Exception as exc:
        portfolio_logger.warning(f"Collision check failed (non-fatal): {exc}")
        return None
```

**Why `(provider, institution_slug)` and not `(provider, display_name)`**: the registry's ambiguity check at `services/account_registry.py:209` keys on `(user_id, provider, institution_slug)` — that's the canonical "two rows for the same connection" identity in this codebase. Display names are derived (`_DEFAULT_INSTITUTION_NAMES.get(provider_token)` or input from various entry points) and can be null or vary in casing/whitespace. Deduping on display name would let two rows with the same slug but different cosmetic names both survive into the payload.

**Critical: use `normalize_institution_slug()` (from `providers/routing.py`), NOT the local `_slugify()`**. The two produce different output for IBKR (`normalize_institution_slug("IBKR") == "interactive_brokers"`, but `_slugify("IBKR") == "ibkr"`). The `data_sources.institution_slug` column is populated via `normalize_institution_slug` in the brokerage lifecycle, so the WHERE clause must match.

`POSITION_PROVIDERS` is a `set` — must cast to `list()` for `psycopg ANY(%s)`.

**`import_portfolio()` signature (line 260)**: insert `force: bool = False` after `source_key` and before `user_email`.

**Collision computation — gated so it only runs when actually needed**

The lookup must run for dry-run (always informational) AND for the real-import path *only after* the validation-error guard passes. Insert this helper closure right after line 311 (`computed_source_key = ...`):

```python
def _compute_collision() -> dict[str, Any] | None:
    institution_slug = normalize_institution_slug(result.brokerage_name)
    colliding_sources = _check_api_collision(institution_slug, resolved_user_email)
    if not colliding_sources:
        return None
    return {
        "institution_slug": institution_slug,
        "active_api_connections": [
            {
                "provider": str(s.get("provider") or ""),
                "institution": s.get("institution_display_name") or institution_slug,
            }
            for s in colliding_sources
        ],
    }
```

**In the dry-run branch (line 316)**: call `collision = _compute_collision()` as the first line inside the branch, before constructing the response dict.

**In the real-import path**: call `collision = _compute_collision()` *after* the `if result.errors:` return (line 335-346) and *before* the new `if collision and not force:` block. This guarantees a parsing-failed CSV never triggers a wasted DB query AND establishes the unambiguous "validation errors return first" ordering.

**Dry-run branch (line 316-333)**:
- Change `can_import` to: `can_import = not result.errors and not (collision and not force)`
- When `collision` is truthy, add `"collision": collision` to the response. When `None`, omit the key entirely (avoids breaking exact-match preview tests; frontend uses `Boolean(preview?.collision)` for discrimination).
- When `collision and not force`, override `message` to: `f"{result.brokerage_name} already has active API connection(s) — importing this CSV would create duplicate positions. Re-run with force=true to import anyway."`

Implementation pattern:
```python
response: dict[str, Any] = {
    "status": "ok",
    "action": "import",
    "dry_run": True,
    "can_import": can_import,
    # ...existing fields...
}
if collision:
    response["collision"] = collision
return response
```

**Real-import collision block — insert AFTER the existing `if result.errors:` return block (line 335-346) and BEFORE `provider.save_positions(...)` (line 348)**:
```python
if collision and not force:
    providers_str = ", ".join(c["provider"] for c in collision["active_api_connections"])
    return {
        "status": "collision_blocked",
        "action": "import",
        "dry_run": False,
        "brokerage_name": result.brokerage_name,
        "source_key": computed_source_key,
        "positions_found": len(position_dicts),
        "collision": collision,
        "warnings": list(result.warnings),
        "errors": [],
        "message": (
            f"Import blocked: {result.brokerage_name} already has active API connection(s) "
            f"via {providers_str}. Importing this CSV would create duplicate positions. "
            "Pass force=true to override."
        ),
    }
```

**Order rationale**: in the real-import path, the `_compute_collision()` call is placed AFTER the validation-error return guard. If `result.errors` is non-empty, the function returns at line 335-346 and the collision lookup never runs — no wasted DB query, no ambiguity about ordering. This matches `mcp_tools/import_transactions.py:270` which returns validation errors before any further work.

**Dry-run is collision-aware but does not gate on validation errors**: the dry-run branch (line 316-333) is informational. It calls `_compute_collision()` first thing inside the branch, regardless of `result.errors`, and includes `collision` in the response when truthy. The frontend uses the `collision` field to show the inline banner; existing validation-error rendering is unchanged. The plan does NOT add a "validation errors block confirm" gate to the preview UI — that's out of scope and would change behavior orthogonal to F16.

**Success response (line 359)**: add `"collision_override": bool(collision)` to the returned dict.

### Phase 2 — MCP wrapper

**`mcp_server.py:425-444`**: add `force: bool = False` to the `import_portfolio()` wrapper signature after `source_key`, before `user_email`. Pass through to `_import_portfolio(...)` at line 437.

### Phase 3 — Web routes

**`routes/onboarding.py`**

`_shape_csv_error()` (line 158): after the existing `if "brokerage_name" in result:` block (~line 169), add:
```python
if "collision" in result:
    payload["collision"] = result.get("collision")
```
This makes the shaper pass `collision` through for any result that carries it (covers `collision_blocked` AND any future error path that might surface collision context).

`/preview-csv` (line 697-732): no new form field. In the success branch (line 725-732), conditionally add `collision` to the returned dict ONLY when present:
```python
collision = result.get("collision")
payload = {
    "status": "success",
    "positions_count": int(result.get("positions_found") or 0),
    "total_value": round(float(result.get("total_value") or 0.0), 2),
    "sample_holdings": _map_preview_holdings(list(result.get("preview") or [])),
    "warnings": list(result.get("warnings") or []),
    "source_key": result.get("source_key"),
}
if collision:
    payload["collision"] = collision
return payload
```
**Why omit when null**: the existing exact-match test at `tests/routes/test_onboarding.py:1333` asserts the success payload as a dict literal with no `collision` key. Omitting when null preserves backward compatibility and avoids touching unrelated tests. The frontend already discriminates with `Boolean(preview?.collision)` (key-absent ≡ key-null for that check).

The `_shape_csv_error()` shaper already passes `collision` through unconditionally (Phase 3 edit above) — that's fine for error/needs_normalizer paths because they have no exact-match tests on the response shape.

`/import-csv` (line 735-769):
- Add `force: bool = Form(False)` after `institution`.
- Pass `force=force` to `import_portfolio(...)`.
- The existing `if result.get("status") != "ok":` guard (line 760) already routes to `_shape_csv_error()`, which now propagates `collision`. Returning HTTP 200 happens automatically (no `raise HTTPException` needed). Verified: `_shape_csv_error` returns the dict directly with `status` set from `result.get("status")` (line 160), so `"status": "collision_blocked"` flows through to the JSON body.

`/import-csv-full` (line 772-798): identical edits — add `force` form field, pass through.

### Phase 4 — Frontend collision UI

**4a. Preview type — `CsvImportStep.tsx` (line 17-34)**

Add `collision` field to `CsvPreviewResponse`. Do NOT add `'collision_blocked'` to its `status` union — `/preview-csv` never returns that status; the collision is informational on the preview path:
```ts
export interface CsvPreviewResponse {
  status: 'success' | 'error' | 'needs_normalizer';
  // ...existing fields...
  collision?: {
    institution_slug: string;
    active_api_connections: Array<{ provider: string; institution: string }>;
  } | null;
}
```

Extend `CsvImportSelection` interface (line 36-41): add `force?: boolean;`.

**4b. Import-completion type — `useOnboardingActivation.ts` (line 39-50)**

Widen `CsvImportCompletionResponse` so the Onboarding/Empty paths can express the new status without TypeScript errors:
```ts
export interface CsvImportCompletionResponse {
  status: 'success' | 'error' | 'needs_normalizer' | 'collision_blocked';
  message?: string;
  // ...existing fields...
  collision?: {
    institution_slug: string;
    active_api_connections: Array<{ provider: string; institution: string }>;
  } | null;
}
```

**No runtime change required in `beginCsvImport` (line 192-260)**: the existing fall-through at line 241-248 already routes any non-`success` result to `phase: 'error'` with `result.message`. The collision message ("Import blocked: X already has active API connection(s) via Y...") is self-explanatory and displays directly in the error completion screen.

**4c. Settings full-import type — `CsvImportCard.tsx` (line 17-24)**

Widen the local `CsvImportFullResponse` interface the same way:
```ts
interface CsvImportFullResponse {
  status: 'success' | 'error' | 'needs_normalizer' | 'collision_blocked';
  // ...existing fields...
  collision?: {
    institution_slug: string;
    active_api_connections: Array<{ provider: string; institution: string }>;
  } | null;
}
```

**No runtime change required in `handleConfirm` (line 33-87)**: existing logic at line 55-57 throws `new Error(response.message ?? ...)` for any non-success response, which the `catch` block at line 80-86 toasts. The collision message displays in the toast verbatim.

**Recovery flow (settings)**: after the toast, the `CsvImportStep` is still mounted with the same stale `preview` state. No retry/submit path inside `CsvImportStep` triggers a fresh preview — `requestPreview` is only called from `handleFileChange` (line 138), `handleInstitutionChange` (line 153), `handleNormalizerActivated` (line 191), and the "Select institution manually" button inside the needs-normalizer card (line 329). None of these fire from re-clicking "Confirm import". **The reliable settings-card recovery path is collapsing the card via the "Hide import" toggle (`CsvImportCard.tsx:111`, which unmounts `CsvImportStep` due to the `isExpanded` conditional) and re-expanding it (which remounts a fresh component with empty state).** Same-file re-selection in the file picker is unreliable: HTML file inputs typically do not fire `change` when the user picks the same file twice because the input value is not reset between selections. Documented as accepted; no code changes to add an explicit "retry" button — the rare race doesn't warrant new UI surface area.

**4d. Component state + banner — `CsvImportStep.tsx`**

Add state:
```ts
const [collisionAcknowledged, setCollisionAcknowledged] = useState(false);
```

Reset `collisionAcknowledged` to `false` inside `requestPreview` (~line 87, alongside existing state resets).

Render a **collision banner** above the bottom button row (~line 408), shown when `preview?.status === 'success' && preview.collision`:
- Title: `"This institution is already connected via API"`
- Body: `preview.collision.active_api_connections.map(c => c.provider).join(", ")` + sentence explaining duplicate risk.
- Acknowledgment checkbox: `"Yes, I understand — import anyway and create duplicate positions"` bound to `collisionAcknowledged`.
- Use design tokens (`border-[hsl(var(--down))]`, `text-[hsl(var(--down))]`) consistent with the existing error card pattern at line 279.

Confirm button `disabled` (line 415):
```ts
disabled={
  !selectedFile ||
  preview?.status !== 'success' ||
  isPreviewing || isSubmitting ||
  (Boolean(preview?.collision) && !collisionAcknowledged)
}
```

`handleConfirm` (line 195-212): pass `force: Boolean(preview?.collision) && collisionAcknowledged` into the `onConfirm({...})` selection.

Confirm dialog (line 423-456): when `preview?.collision` is present, swap the title to `"Import anyway?"` and the description to emphasize duplicate risk + list providers. Primary button label becomes `"Import anyway (creates duplicates)"`.

**4e. Three parent callsites — thread `selection.force` into FormData**

1. `OnboardingWizard.tsx:59-90` (`uploadCsv`) — after `formData.append('institution', selection.institution)`:
```ts
if (selection.force) {
  formData.append('force', 'true');
}
```

2. `EmptyPortfolioLanding.tsx:73-95` — same edit.

3. `CsvImportCard.tsx:33-87` (`handleConfirm`) — same edit.

**4f. Race-window handling (rare path)**

When the preview returned no collision but the import returns `status: "collision_blocked"` — e.g., user connected another broker in a parallel tab between preview and confirm, OR DB was briefly unavailable during preview — the existing error paths handle it without code changes. Recovery requires the user to trigger a fresh preview. No retry or submit path inside `CsvImportStep` triggers `requestPreview()` — only `handleFileChange` (line 138), `handleInstitutionChange` (line 153), `handleNormalizerActivated` (line 191), and the "Select institution manually" button in the needs-normalizer card (line 329) call it.

- **Onboarding wizard**: `beginCsvImport` (`useOnboardingActivation.ts:241-248`) sets `phase: 'error'` and routes the user to the `CompletionStep` (`OnboardingWizard.tsx:216`) showing `result.message` (the full collision warning string from the backend). Clicking the screen's `onRetry` re-invokes `uploadCsv(lastCsvSelection)` with the same stale selection — still `force=false`, still no fresh preview — and they land back on the same error screen. **The reliable recovery path is `onSkipForNow`/`dismissToLanding` (`OnboardingWizard.tsx:225` → line 77), which calls `reset()` and `onDismiss?.()`, dropping the user back to `EmptyPortfolioLanding` (the parent). From there the user clicks "Import a CSV" (`EmptyPortfolioLanding.tsx:160`, which calls `reset()` + `setStage('csv')`), re-selects the file, and the fresh preview catches the collision → inline banner.**
- **Empty landing**: `beginCsvImport` sets `phase: 'error'` and routes to the embedded `CompletionStep` (`EmptyPortfolioLanding.tsx:218-249`). The screen's `onSkipForNow` handler at line 248 only writes `localStorage` (line 100) — it does NOT reset the flow or unmount the completion step. **The reliable recovery path is the persistent "Import a CSV" button at `EmptyPortfolioLanding.tsx:160-173`, which is always visible above the stage area and calls `reset()` + `setSelectedInstitution('')` + `setSelectedProvider('')` + `setSelectedSupport(null)` + `setFlowMode('csv')` + `setStage('csv')` — this remounts `CsvImportStep` with empty state. The user re-selects the file and the fresh preview catches the collision.**
- **Settings card**: `handleConfirm` throws → catch block toasts `error.message` (the collision warning). The `CsvImportStep` stays mounted with stale state. **The reliable recovery path is the "Hide import" toggle (`CsvImportCard.tsx:111`, the `{isExpanded ? <CsvImportStep ... /> : null}` conditional) — collapsing unmounts `CsvImportStep`, re-expanding remounts it fresh.** Same-file re-selection is not reliable because the file input value isn't reset between picks.

The recovery path costs the user 2-3 extra clicks but does not require new state machine stages or additional UI surface area. Documented as accepted given the rarity of the race window.

### Phase 5 — Tests

**Tool-level: `tests/mcp_tools/test_import_portfolio.py` (9 tests)**

Existing tests in this file monkeypatch `import_portfolio_tool.detect_and_normalize` and pass through the real `import_portfolio()`. The new tests follow the same pattern, additionally monkeypatching `import_portfolio_tool._check_api_collision` to return canned dicts (avoiding DB).

| # | Test | Scenario |
|---|------|----------|
| 1 | `test_dry_run_collision_warns_and_blocks` | Mock collision returned, `force=False`, `dry_run=True` → `can_import=False`, `collision` dict in response, warning message |
| 2 | `test_dry_run_collision_with_force_allows` | Mock collision, `force=True`, `dry_run=True` → `can_import=True`, `collision` still present |
| 3 | `test_dry_run_no_collision_omits_key` | No collision (helper returns None) → response dict has NO `collision` key |
| 4 | `test_import_blocked_by_collision` | `dry_run=False`, `force=False`, mock collision → `status == "collision_blocked"`, `provider.save_positions` NOT called (use a spy) |
| 5 | `test_import_with_force_overrides_collision` | `dry_run=False`, `force=True`, mock collision → `status == "ok"`, `collision_override=True`, save_positions called once |
| 6 | `test_collision_helper_returns_none_when_db_unavailable` | Monkeypatch `is_db_available` → False → `_check_api_collision` returns None; import proceeds normally |
| 7 | `test_collision_helper_returns_none_on_db_exception` | Monkeypatch `get_db_session` to raise → helper returns None, import proceeds |
| 8 | `test_collision_uses_normalize_institution_slug` | Patch the SELECT execution; assert WHERE param receives `"interactive_brokers"` (NOT `"ibkr"`) when `brokerage_name="IBKR"`. Guards the slug-mismatch gotcha. |
| 9 | `test_validation_errors_beat_collision` | `result.errors` non-empty AND collision present, `dry_run=False` → returns `status="error"` validation response, NOT `collision_blocked`. Locks in error-ordering. |

**Route-level: `tests/routes/test_onboarding_csv_collision.py` (new, 6 tests)**

Patch `routes.onboarding.import_portfolio` to return canned dicts.

| # | Test | Scenario |
|---|------|----------|
| 1 | `test_preview_csv_forwards_collision` | Patched returns dry-run dict with `collision` → POST `/preview-csv` returns 200, body has `collision` dict |
| 2 | `test_preview_csv_no_collision_omits_key` | Patched returns `collision=None` → preview body has NO `collision` key (preserves exact-match contract for `tests/routes/test_onboarding.py:1333`) |
| 3 | `test_import_csv_collision_blocked_returns_200_with_body` | Patched returns `status="collision_blocked"` → POST `/import-csv` multipart, no `force` → **HTTP 200**, body has `status: "collision_blocked"`, collision dict, message. (Asserts the no-409 design choice.) |
| 4 | `test_import_csv_force_true_is_threaded_through` | POST `/import-csv` with `data={"force": "true"}`, patched `import_portfolio` asserts kwargs received `force=True`. Success response returned. |
| 5 | `test_import_csv_full_collision_blocked_returns_200_with_body` | Same as #3 but `/import-csv-full` |
| 6 | `test_import_csv_full_force_true_is_threaded_through` | POST `/import-csv-full` with `data={"force": "true"}`, patched `import_portfolio` asserts kwargs received `force=True`. Success response returned. Locks force-threading for the settings entry point. |

**Frontend tests (new file, optional but strongly encouraged): `frontend/packages/ui/src/components/onboarding/__tests__/CsvImportStep.collision.test.tsx`**

Use vitest + React Testing Library (mirror the setup of any nearby existing test). 4 tests:

1. Renders collision banner when `preview.collision` is present.
2. Confirm button is disabled until `collisionAcknowledged === true`.
3. `handleConfirm` invokes `onConfirm` with `{ force: true }` when collision + acknowledged.
4. No banner when `preview.collision` is null.

**Total: 15 backend tests (9 tool + 6 route) + 4 optional frontend tests.** F17 already covers the 9 service-level/disconnect tests from the tabled plan (verified in `tests/services/test_account_registry.py`, `tests/routes/test_plaid_disconnect.py`, `tests/routes/test_snaptrade_disconnect.py`, `tests/brokerage/test_snaptrade_recovery.py`).

## Out of Scope / Known Limitations

1. **Schwab/IBKR connect-time false-negative window**: `data_sources` rows for Schwab/IBKR are only created on first successful refresh (`routes/onboarding.py:623,672`), not at connection time. A user who connects Schwab and immediately CSV-imports before running a refresh will not see a collision. This is a pre-existing condition F17 did not address. Proper fix is to create rows in the OAuth/gateway connect handlers — left as future work.
2. **Auto-recovery on race**: if a collision appears between preview and confirm (user connected an API in another tab, or DB was briefly unavailable during preview), Onboarding/Empty users land on the `CompletionStep` error screen with the collision message; settings users see a toast. Recovery requires triggering a fresh preview through one of the reliable paths: (a) Onboarding wizard — `dismissToLanding` then "Import a CSV" from `EmptyPortfolioLanding`; (b) Empty landing — the persistent "Import a CSV" button at line 160; (c) Settings — collapse and re-expand the import card via the "Hide import" toggle. Same-file file-input re-selection is unreliable. See Phase 4f for the detailed flow. No new state machine stages or UI surface added.

## Verification

1. Run existing tests:
   ```
   pytest tests/mcp_tools/test_import_portfolio.py -v
   ```
2. Run all 15 new backend tests:
   ```
   pytest tests/mcp_tools/test_import_portfolio.py tests/routes/test_onboarding_csv_collision.py -v
   ```
3. Run frontend tests if Phase 4 tests are added:
   ```
   cd frontend && npm test -- CsvImportStep.collision
   ```
4. **Manual MCP**: `import_portfolio(file_path=..., brokerage="schwab", dry_run=True)` against a user with an active Schwab API connection → collision warning in dry-run response.
5. **Manual MCP**: same call with `force=True, dry_run=False` → success with `collision_override=True`.
6. **Manual frontend (settings)**: Connect Schwab via SnapTrade. Open Settings → Import Portfolio CSV. Upload a Schwab CSV → preview shows collision banner. Without acknowledging, confirm button is disabled. Acknowledge → button enables → import succeeds. Note: `collision_override=True` is added to the `import_portfolio()` response (Phase 1) and visible via MCP (step 5), but NOT surfaced by the `/import-csv-full` route which builds its own success payload (`routes/onboarding.py:825`). Verify the import completed successfully via the frontend toast.
7. **Manual frontend (onboarding)**: Same flow via `OnboardingWizard` and `EmptyPortfolioLanding`.
8. **Manual disconnect verification**: Disconnect Schwab → `data_sources.status` becomes `disconnected` (F17 behavior). Re-upload same CSV → no collision banner.
9. **Slug regression**: Test with `brokerage="IBKR"` and `brokerage="Interactive Brokers"` — both should match an `interactive_brokers` data_source row.

## Open Questions for Codex Review

1. **HTTP 200 vs 409**: Plan locks in 200-with-status-discriminator for the load-bearing HttpClient constraint reasons documented above. Codex should challenge: would a minimal HttpClient body-parse for 409 (mirroring the 403 upgrade-required path) be cleaner? Recommendation: no — adds cross-package coupling for one feature.
2. **Validation errors before collision check**: plan returns validation errors first. Acceptable, or should collision warnings flow alongside validation errors in a combined response?
3. **Force-override UX — checkbox vs destructive button**: plan uses an in-banner checkbox + re-uses the primary confirm button. Codex DX review may prefer an explicit destructive button. Either is defensible.
4. **Dry-run `collision` key omitted when null**: plan locks in "key present only when truthy" to preserve the exact-match assertion at `tests/routes/test_onboarding.py:1333`. Frontend uses `Boolean(preview?.collision)` so absent and null are equivalent. Should this remain the contract, or should we add the null sentinel and update the existing test?
5. **Frontend test count**: plan treats 4 frontend tests as "strongly encouraged but optional". Should they be required?
6. **`Optional[bool] = Form(False)` typing**: plan uses non-Optional `bool = Form(False)`. Verify against existing FastAPI form param patterns in `routes/`.
7. **`POSITION_PROVIDERS` cast**: plan uses `list(POSITION_PROVIDERS)` for `psycopg ANY(%s)`. Verify with existing `ANY(%s)` usage in the repo.

## Risks

1. **Slug mismatch (caught by test #8)**: if implementer uses `_slugify(result.brokerage_name)` instead of `normalize_institution_slug(...)`, IBKR CSVs will never match `interactive_brokers` data_source rows. This is the #1 silent-failure mode.
2. **Collision check insertion point**: must go AFTER line 311 (`computed_source_key = ...`) — earlier and the variable is undefined in the `collision_blocked` return branch.
3. **Schwab/IBKR connect-time window**: documented above. Acceptable.
4. **Forgetting one of three frontend callsites**: `OnboardingWizard.uploadCsv` (line 59-90), `EmptyPortfolioLanding.uploadCsv` (line 73-95), and `CsvImportCard.handleConfirm` (line 33-87, posts directly without an `uploadCsv` helper) each build their own FormData. Missing the `force` append in any one leaves a dead UI path. Plan enumerates all three explicitly in Phase 4e.
5. **`_shape_csv_error` status preservation**: shaper reads `result.get("status") or "error"` (line 160). The plan's `collision_blocked` return path explicitly sets `"status": "collision_blocked"`, so the shaper passes it through. Verified.
6. **Race window between preview and import**: accepted; user retries.
7. **Parallel session drift**: line numbers cited above are from the working tree on 2026-04-08. Codex must re-read each file before applying edits and reconcile any drift from concurrent work.

## Critical Files

- `/Users/henrychien/Documents/Jupyter/risk_module/mcp_tools/import_portfolio.py`
- `/Users/henrychien/Documents/Jupyter/risk_module/mcp_server.py`
- `/Users/henrychien/Documents/Jupyter/risk_module/routes/onboarding.py`
- `/Users/henrychien/Documents/Jupyter/risk_module/providers/routing.py` (read-only — supplies `normalize_institution_slug` + `POSITION_PROVIDERS`)
- `/Users/henrychien/Documents/Jupyter/risk_module/services/account_registry.py` (read-only — F17 status-aware queries already in place)
- `/Users/henrychien/Documents/Jupyter/risk_module/frontend/packages/app-platform/src/http/HttpClient.ts` (read-only — drives the no-409 decision)
- `/Users/henrychien/Documents/Jupyter/risk_module/frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx`
- `/Users/henrychien/Documents/Jupyter/risk_module/frontend/packages/ui/src/components/onboarding/OnboardingWizard.tsx`
- `/Users/henrychien/Documents/Jupyter/risk_module/frontend/packages/ui/src/components/onboarding/EmptyPortfolioLanding.tsx`
- `/Users/henrychien/Documents/Jupyter/risk_module/frontend/packages/ui/src/components/onboarding/useOnboardingActivation.ts`
- `/Users/henrychien/Documents/Jupyter/risk_module/frontend/packages/ui/src/components/settings/CsvImportCard.tsx`
- `/Users/henrychien/Documents/Jupyter/risk_module/tests/mcp_tools/test_import_portfolio.py`
- `/Users/henrychien/Documents/Jupyter/risk_module/tests/routes/test_onboarding_csv_collision.py` (new)
