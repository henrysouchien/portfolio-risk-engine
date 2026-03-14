# Copy Review — Outcome-Focused Language Pass

**Status**: TODO
**Created**: 2026-03-13
**Goal**: Audit all user-facing copy for clarity, tone, and outcome focus. Replace feature-speak and technical jargon with language that tells users what they can *do* and what they'll *get*.

---

## Principle

Every piece of text the user reads should answer: **"What does this do for me?"** — not "what is this feature called" or "what technology powers it."

Bad: "AI-powered risk monitoring with real-time factor analysis"
Good: "Get alerted when your portfolio risk changes"

Bad: "Comprehensive portfolio monitoring"
Good: "See all your accounts in one place"

---

## Surfaces to Review

### 1. Landing Page (pre-auth)
**File**: `frontend/packages/ui/src/components/auth/LandingPage.tsx`

- [ ] Headline — does it say what the product does for the user?
- [ ] Tagline — outcome or feature list?
- [ ] Feature bullets — "you get X" vs "we have X"?
- [ ] CTA button labels — clear action?
- [ ] Any jargon a non-quant investor wouldn't understand?

### 2. Onboarding Wizard
**Files**: `frontend/packages/ui/src/components/onboarding/`

- [ ] Step titles — do they orient the user on what's happening?
- [ ] Step descriptions — clear on what the user needs to do and why?
- [ ] Provider selection copy — does a new user understand what "Connect via Plaid" means?
- [ ] CSV import messaging — is "needs_normalizer" translated to human language?
- [ ] Empty state / loading copy during import
- [ ] Error messages — actionable or cryptic?
- [ ] Success states — does the user know what happens next?

### 3. Dashboard / Overview
**Files**: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`, card components

- [ ] Card titles — meaningful to a user who just signed up?
- [ ] Empty states — what do cards say when there's no data yet?
- [ ] Metric labels — would a retail investor understand "Sharpe Ratio" without the tooltip?
- [ ] AI Insights panel — is the language advisory or just data dump?
- [ ] Market Intelligence — are event descriptions actionable?

### 4. Section Headers & Navigation
**Files**: Nav items, view headers, tab labels

- [ ] "Research" / "Scenarios" / "Trading" / "Performance" — are these the right words for the audience?
- [ ] Sub-view labels — "Stress Test", "What-If", "Monte Carlo" — too technical?
- [ ] Tooltips on nav items — do they exist? Should they?

### 5. AI Chat / Assistant
**Files**: `frontend/packages/ui/src/components/chat/`

- [ ] Welcome message — does it help a new user know what to ask?
- [ ] Suggested prompts — outcome-focused or feature-focused?
- [ ] Tool approval copy — does the user understand what they're approving?
- [ ] Error/retry messages

### 6. Settings
**Files**: `SettingsPanel.tsx`, `AccountConnections.tsx`, `RiskSettingsViewModern.tsx`

- [ ] Section labels and descriptions
- [ ] Risk limit labels — meaningful to non-quant users?
- [ ] Account connection status messages
- [ ] Save/cancel/reset button labels

### 7. Error States & Edge Cases
Across all views:

- [ ] API error messages — generic "Something went wrong" vs helpful guidance?
- [ ] Empty portfolio state — what does the user see and what should they do?
- [ ] Loading messages — "Loading..." vs something useful?
- [ ] Disconnected provider warnings — clear on impact and action needed?

---

## Tone Guidelines

- **Direct**: Say what it does, not what it is
- **Second person**: "Your portfolio" not "The portfolio"
- **Active voice**: "See your risk breakdown" not "Risk breakdown is displayed"
- **No marketing fluff**: No "powerful", "comprehensive", "intelligent", "cutting-edge"
- **No false claims**: If we don't have SOC 2, don't say we do
- **Jargon budget**: Finance terms are OK when they're the right term (VaR, Sharpe). But always pair with context on first encounter
- **Brevity**: If a label can be 2 words, don't make it 5

---

## Deliverables

1. **Findings spreadsheet** — surface, current copy, proposed copy, severity (misleading / unclear / fine but could improve)
2. **Code changes** — update copy in components. Most changes are string literals, very low risk.
3. **Glossary decisions** — list of finance terms we keep vs. simplify, with rationale

## Scope

- **In scope**: All user-visible text — headlines, labels, descriptions, tooltips, error messages, empty states, button text, placeholder text
- **Out of scope**: Code comments, console logs, API response messages (backend-only), documentation
- **Priority**: Landing page and onboarding first (first impression), then dashboard, then deep views
