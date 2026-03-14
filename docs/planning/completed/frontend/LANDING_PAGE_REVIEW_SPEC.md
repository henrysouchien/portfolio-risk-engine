# Landing Page Review — Onboarding & Design Evaluation

**Status**: TODO
**Created**: 2026-03-13
**Goal**: Evaluate the pre-auth landing page from a new user's perspective. Fix copy, design, trust claims, and first-impression issues before launch.

---

## Context

The landing page (`LandingPage.tsx`) is the first thing a new user sees. It was built as part of the auth system but has never been evaluated from a product/design perspective. It needs a fresh-eyes review before we ship.

## Key Files

| File | Role |
|------|------|
| `frontend/packages/ui/src/components/auth/LandingPage.tsx` | Presentational UI (~420 lines, pure rendering) |
| `frontend/packages/ui/src/pages/LandingPage.tsx` | Container/logic layer (auth state, error handling) |
| `frontend/packages/ui/src/components/auth/GoogleSignInButton.tsx` | Google OAuth button integration |
| `frontend/packages/ui/src/components/apps/AppOrchestratorModern.tsx` | Routes unauthenticated users here |

## Current Structure

```
Hero Section
  - Gradient TrendingUp icon
  - "Portfolio Risk Engine" headline
  - "Professional Investment Tools" badge
  - Tagline about intelligent risk assessment

Two-card layout (side-by-side):
  Left: "Full Integration" — Google Sign-In, 4 feature bullets
  Right: "Instant Try" — file upload (PDF/CSV/XLSX/YAML), no account needed

Trust badges footer:
  - "Trusted by investors worldwide"
  - "Bank-grade security" / "SOC 2 compliant" / "GDPR compliant"
```

## Evaluation Checklist

### 1. Trust Claims Audit (CRITICAL)
- [ ] **"SOC 2 compliant"** — Is this actually true? If not, remove immediately. False compliance claims are a liability.
- [ ] **"GDPR compliant"** — Same. Do we have a privacy policy, data deletion flow, cookie consent?
- [ ] **"Bank-grade security"** — Vague but common. Acceptable if we have TLS + encrypted storage. Verify.
- [ ] **"Trusted by investors worldwide"** — If there are no external users yet, this is misleading. Remove or replace.

### 2. Copy & Messaging
- [ ] Is "Portfolio Risk Engine" the right product name for the landing page? Too technical?
- [ ] Does the tagline clearly communicate what the product does for the user (not what it is)?
- [ ] Are the 4 feature bullets under "Full Integration" compelling and accurate?
- [ ] Does "Instant Try" clearly explain what happens when you upload a file?
- [ ] Is the distinction between the two cards clear to a first-time visitor?

### 3. Design & First Impression
- [ ] Does it look like a real product or a template/demo?
- [ ] Are the floating gradient orbs and glass morphism appropriate for a finance product?
- [ ] Does the page load quickly? Any layout shift?
- [ ] Mobile responsive — does the two-card layout stack properly?
- [ ] Dark mode — does it look good in both themes?
- [ ] Is the Google Sign-In button visually prominent enough?

### 4. "Instant Try" Flow Verification
- [ ] Does the `/try` route actually work end-to-end?
- [ ] What happens after file upload? Does the user see results?
- [ ] If this flow is broken or incomplete, should we hide it? (`ENABLE_INSTANT_TRY` flag exists)
- [ ] Is the file type list correct (PDF, CSV, XLSX, YAML)?

### 5. Auth UX
- [ ] What happens on auth failure? Is the error message clear?
- [ ] Loading state during Google OAuth — is there feedback?
- [ ] Cross-tab logout — does it work?
- [ ] What does the user see if Google OAuth is misconfigured (no client ID)?

### 6. Onboarding Continuity
- [ ] After sign-in, what's the transition? Smooth or jarring?
- [ ] Does the user land on the onboarding wizard or the dashboard?
- [ ] Is there a clear path from "I just signed in" to "I see my portfolio"?

## Deliverables

1. **Findings doc** — list of issues with severity (blocker / should-fix / nice-to-have)
2. **Copy rewrites** — if the messaging needs work, propose alternatives
3. **Code changes** — fix trust claims, broken flows, and design issues
4. **Screenshots** — before/after if visual changes are made

## How to Evaluate

1. Start the frontend dev server (`cd frontend && npm run dev`)
2. Open in a fresh browser profile (no existing auth state)
3. Walk through the page as a brand new user
4. Try the Google Sign-In flow
5. Try the "Instant Try" flow with a sample CSV
6. Check mobile viewport (Chrome DevTools responsive mode)
7. Check dark mode toggle
8. Note everything that feels off, unclear, or untrustworthy

## Scope Boundaries

- **In scope**: Copy, layout, trust claims, auth UX, "Instant Try" verification, mobile, dark mode
- **Out of scope**: Post-auth onboarding wizard (covered by 3I), backend changes, new features
- **Bias toward removal**: If something is misleading or broken, remove it rather than trying to fix it. Ship honest over impressive.
