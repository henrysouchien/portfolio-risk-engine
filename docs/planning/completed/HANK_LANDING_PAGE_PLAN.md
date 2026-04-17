# Plan: Landing/Login Page Rebrand — Hank Identity + DESIGN.md

## Context

The product has been rebranded to **Hank** (`hank.investments`). The sidebar, InsightSection CTA, and ScenariosLanding already say "Hank". But the landing page still says "PortfolioRisk Pro" with generic SaaS copy — it's the first thing users see and the last page to catch up.

**Goal**: Rebrand the landing page to reflect Hank's identity, voice, and DESIGN.md aesthetics. The page should feel like opening a dispatch from your analyst, not signing up for a SaaS product.

---

## Codex Review Log

### R1 FAIL → R2 (5 findings addressed)
1. **GoogleSignInButton error/loading states are off-brand** — Brought into scope (File 7).
2. **"Something went wrong" is too soft for Hank** — Changed to "Sign-in failed".
3. **Missed brand strings in 3 dashboard files** — Added Files 8-10.
4. **`theme-color` meta tag not addressed** — Added to Files 4-5.
5. **Helper line below button leads with plumbing** — Dropped entirely.

### R2 FAIL → R3 (5 findings addressed)
1. **GoogleSignInButton loading text too generic** — Changed from bare "Loading…" to "Preparing sign-in…" in `text-[hsl(var(--ink))]` (analyst voice + `--ink` per BRAND.md loading states and DESIGN.md §Loading states).
2. **Missed RiskMetrics.tsx "Portfolio Risk Analysis" heading** — Added File 10.
3. **DashboardLayout.test.tsx not updated** — Added File 11 to update test assertion.
4. **manifest.json `theme_color` left at `#000000`** — Updated to `#0F1115` for PWA chrome consistency.
5. **`recovery/risk-analysis-dashboard.tsx` has 2 old brand strings** — This file is in `shared/recovery/` and is dead code (not imported anywhere in the codebase). Noted as out-of-scope dead code, not worth touching.

### R3 FAIL → R4 (1 finding addressed)
1. **Remaining "Portfolio Risk" strings in `descriptors.ts`, `AnalysisReportAdapter.ts`, `PortfolioRiskMetricsSlot.tsx`, `ViewIntegrationExample.tsx`** — Domain terminology, not brand. Added §Brand vs. Domain Terminology.

### R4 FAIL → R5 (2 findings addressed)
1. **`RiskMetrics.test.tsx:61`** — Added File 12.
2. **`dashboard-basic-testing.spec.js:18`** — Added File 13.

### R5 FAIL → R6 (2 findings addressed)
1. **`tests/frontend/unit/components/auth/LandingPage.test.js`** — Stale test. Added File 14.
2. **`tests/frontend/integration/auth-flow.test.js`** — Stale test. Added File 15.

### R6-R7 FAIL → R8 (3 findings addressed)
1. **Stale tests reference removed "Instant Try" flow** — Files 14-15 and two more stale test files (`App.test.js`, `analyze-risk-workflow.spec.js`) test against an old UI with upload/instant-try flows that no longer exist. These 4 root-level test files are all already broken against the current codebase. Plan updated: delete all 4 stale test files rather than surgically update dead assertions. Added Files 16-17.
2. **`tests/frontend/App.test.js` not in scope** — Added as File 16 (delete).
3. **Generated artifact rationale incorrect** — Fixed: the "Portfolio Risk Engine" string in `openapi-schema.json` comes from the Plaid client name in `routes/plaid.py`, not the FastAPI app title (which is "Risk Module API").

---

## Files to Modify (17 files: 7 source + 3 metadata + 3 test updates + 4 test deletes)

### 1. `frontend/packages/ui/src/components/auth/LandingPage.tsx` — Main rewrite

This is the presentational component. Rewrite the content while preserving the component contract (`LandingPageProps` with `onGoogleSignIn` + `error`).

**Hero section** — Replace the AppLogo circle + "PortfolioRisk Pro" heading with:
- **Wordmark**: `Hank` as an `<h1>`, ~42-52px, `font-semibold`, `text-ink`, tight tracking (`-0.03em`). Text-only, no logo image. Matches the sidebar brand mark pattern from `AppSidebar.tsx:172` but scaled up.
- **Domain line**: `hank.investments` in Geist Mono section-label style (`font-mono text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--text-dim))]`). Replaces "Portfolio Risk Briefing".
- **Tagline**: "A personal AI investment analyst that actually knows your portfolio." in `text-ink` at 16px (analyst prose register per DESIGN.md). Replaces "See your real risk. Across every account."
- **Remove** the decorative `h-px w-16` divider line.

**Sign-in card** — Strip to minimal:
- Remove `CardHeader` / `CardTitle` ("Get started") / `CardDescription` — SaaS speak.
- Remove `Separator` and `FEATURES` list below the button.
- Card becomes just `GoogleSignInButton` inside a `CardContent` with clean padding. The Google button is self-explanatory — no helper text needed.

**Capabilities footer** — Keep conceptually, update content + style:
- Shorten to single-word domains: `Risk · Factors · Scenarios · Optimization · Execution`
- Apply DESIGN.md section-label style: `font-mono text-[9px] font-semibold uppercase tracking-[0.1em]`

**Error display** — Keep functional structure. Update title from "Sign-in error" to "Sign-in failed" (says what failed, direct, per BRAND.md).

**Layout** — Narrow from `max-w-2xl` to `max-w-lg`. Fewer elements, more editorial column.

**Imports cleanup** — Remove: `TrendingUp`, `BarChart3`, `Brain` (lucide), `AppLogo`, `CardHeader`, `CardTitle`, `CardDescription`, `Separator`.

### 2. `frontend/packages/ui/src/pages/LandingPage.tsx` — Loading state voice

Line 192: `"Signing you in..."` → `"Hank is signing you in…"`

### 3. `frontend/packages/ui/src/components/brand/AppLogo.tsx` — Alt text

- Line 1 JSDoc: "PortfolioRisk Pro brand mark" → "Hank brand mark"
- Line 22 alt: `"PortfolioRisk Pro"` → `"Hank"`

### 4. `frontend/index.html` — Title + meta + theme-color

- Line 9: meta description → `"Hank — a personal AI investment analyst that actually knows your portfolio."`
- Line 11: `<title>` → `Hank`
- Add `<meta name="theme-color" content="#0F1115">` after the viewport meta tag (dark-first browser chrome)

### 5. `frontend/public/index.html` — Title + meta + theme-color

- Line 10: meta description → same as above
- Line 27: `<title>` → `Hank`
- Line 7: `<meta name="theme-color" content="#000000">` → `content="#0F1115"` (match DESIGN.md `--bg`)

### 6. `frontend/public/manifest.json` — PWA names

- `"short_name"`: `"Portfolio Risk"` → `"Hank"`
- `"name"`: `"Portfolio Risk Analysis"` → `"Hank"`
- `"background_color"`: `"#ffffff"` → `"#0F1115"` (dark-first per DESIGN.md)
- `"theme_color"`: `"#000000"` → `"#0F1115"` (match `--bg` for PWA chrome consistency)

### 7. `frontend/packages/ui/src/components/auth/GoogleSignInButton.tsx` — Error/loading voice + design tokens

The button's internal error and loading states use off-brand copy and hardcoded colors that don't match the design system.

- Line 161: `"Loading Google Sign-In..."` → `"Preparing sign-in…"` — in-voice loading copy per BRAND.md/DESIGN.md
- Line 161: `className="text-blue-600"` → `className="text-[hsl(var(--ink))]"` — analyst voice uses `--ink` per DESIGN.md §Loading states
- Line 169: `"Google Sign-In Unavailable"` → `"Google sign-in is not available right now"` — Hank voice, lowercase
- Line 170-171: `"Please refresh the page to try again."` → `"Refresh the page to try again."` — no "please" per Hank directness
- Line 168: `className="bg-red-50 border border-red-200 rounded-lg p-4"` → `className="border border-border rounded-md p-4 bg-surface"` — design system tokens
- Line 169: `className="text-red-800 font-medium"` → `className="text-sm font-medium text-foreground"`
- Line 170: `className="text-red-700 text-sm mt-1"` → `className="text-sm text-muted-foreground mt-1"`

### 8. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — Brand string replacements

Two occurrences of "PortfolioRisk Pro":
- Line 471: `"PortfolioRisk Pro"` → `"Hank"` (loading screen heading)
- Line 472: `"Preparing the analyst briefing..."` → `"Hank is preparing your briefing…"` (loading voice)
- Line 490: `"Welcome to PortfolioRisk Pro"` → `"No portfolio connected"` (no-portfolio state — Hank doesn't say "Welcome to")
- Line 491: `"Connect your accounts or upload a portfolio to get started with AI-powered risk analysis"` → `"Connect a brokerage account or upload a portfolio to get started."` (direct, no buzzwords)

### 9. `frontend/packages/ui/src/components/layouts/DashboardLayout.tsx` — Footer copyright

- Line 56: `"Portfolio Risk Analysis"` → `"Hank"` in the copyright line

### 10. `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx` — Section heading

- Line 195: `"Portfolio Risk Analysis"` → `"Risk Analysis"` — drop the product name from a section heading. This is a data section title, not a brand reference.

### 11. `frontend/packages/ui/src/components/layouts/DashboardLayout.test.tsx` — Test assertion

- Line 24: Update the hardcoded `"Portfolio Risk Analysis"` string in the test assertion to match the new footer copy `"Hank"`.

### 12. `frontend/packages/ui/src/components/portfolio/RiskMetrics.test.tsx` — Test assertion

- Line 61: `"Portfolio Risk Analysis"` → `"Risk Analysis"` to match File 10 source change.

### 13. `tests/integration/dashboard-basic-testing.spec.js` — Integration test

- Line 18: `'Portfolio Risk Analysis'` → `'Hank'` to match updated `<title>` tag.

### 14-17. Stale root-level test files — DELETE

These 4 root-level test files all test against an old UI version that had "Instant Try" buttons, upload flows, and "Portfolio Risk Engine" branding. None of this exists in the current codebase — the tests are already broken. Delete all 4:

- **File 14**: `tests/frontend/unit/components/auth/LandingPage.test.js` — asserts "Portfolio Risk Engine", "Instant Try", upload controls
- **File 15**: `tests/frontend/integration/auth-flow.test.js` — asserts "Portfolio Risk Engine", instant-try-button testid
- **File 16**: `tests/frontend/App.test.js` — asserts `/portfolio risk engine/i`
- **File 17**: `tests/integration/analyze-risk-workflow.spec.js` — depends on `[data-testid="instant-try-button"]`

These are NOT the package-level Vitest tests (which live in `frontend/packages/*/src/`). The package-level tests that assert on changed strings are covered by Files 11-12.

---

## Brand vs. Domain Terminology

The grep gate is "PortfolioRisk Pro" and "Portfolio Risk Analysis" **as a product name** — not every occurrence of "portfolio risk" as a domain concept.

**Brand references (MUST rebrand):** Used as product identity, page titles, HTML `<title>`, manifest names, hero headings, copyright lines, "Welcome to X" greetings.

**Domain terminology (keep as-is):** "Portfolio Risk Score" (tool label in descriptors.ts), "Portfolio Risk Analysis" (tool descriptor label), "Portfolio Risk Metrics" (chart slot title), "Portfolio Risk Contributors" (chart title). These describe analytical features, not the product brand.

**The test:** If replacing the string with "Hank" would sound wrong ("Hank Score", "Hank Metrics"), it's domain terminology, not a brand reference.

---

## What NOT to Change

- `AppSidebar.tsx` — already says "Hank"
- `InsightSection.tsx` — already says "Ask Hank →"
- Container/presentational split — preserved exactly
- All `data-testid` attributes — preserved
- `logo.png` asset — still used by AppLogo in sidebar; replacing the image is a separate design task

---

## Out of Scope

- Sidebar chat label "Analyst" → "Hank" (separate TODO)
- AgentPanel/ChatMargin placeholder text (separate TODO)
- Logo image replacement (separate design task)
- CSV upload / "try without signing in" flow (future feature)
- `frontend/.../shared/recovery/risk-analysis-dashboard.tsx` — dead code (not imported anywhere), has 2 old brand strings. Not worth touching.
- `frontend/openapi-schema.json` + `frontend/packages/chassis/src/types/api-generated.ts` — generated artifacts from the backend OpenAPI schema. The "Portfolio Risk Engine" string originates from the Plaid client name in `routes/plaid.py` (the FastAPI app title is "Risk Module API"). Regenerating these requires a backend change (out of scope for this frontend rebrand).

---

## Verification

1. Start dev server via `services-mcp` (`risk_module` + `risk_module_frontend`)
2. Open `localhost:3000` in browser (unauthenticated state)
3. Verify: hero says "Hank", domain line says "hank.investments", tagline reads correctly
4. Verify: sign-in card is minimal with Google button
5. Verify: capabilities footer shows updated terms in Geist Mono
6. Verify: page works in both light and dark mode
7. Verify: browser tab title says "Hank"
8. Verify: error state renders correctly (trigger via auth store error, e.g. invalid token)
9. Verify: GoogleSignInButton loading/error states use design tokens (no blue/red hardcoded colors)
10. Verify: responsive layout at mobile breakpoint
11. Verify: dashboard loading screen says "Hank" (not "PortfolioRisk Pro")
12. Verify: no-portfolio state says "No portfolio connected" (not "Welcome to PortfolioRisk Pro")
13. Verify: footer copyright says "Hank"
14. Run `cd frontend && npx tsc --noEmit` to confirm no type errors
15. Grep frontend for any remaining "PortfolioRisk Pro" or "Portfolio Risk Analysis" used as product branding (domain terms like "Portfolio Risk Score" are expected — see §Brand vs. Domain Terminology)
