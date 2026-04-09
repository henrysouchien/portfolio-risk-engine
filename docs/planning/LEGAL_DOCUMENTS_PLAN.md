# Legal Documents Implementation Plan

> **Status:** PLANNING
> **Created:** 2026-03-19
> **Priority:** LAUNCH-BLOCKING
> **Depends on:** Pricing tier finalization, LLC formation, hosting provider decision
> **Reference:** `finance_cli/docs/planning/RECOMMENDATION_D4_LEGAL.md` (prior art for finance-cli)

---

## Problem Statement

The risk_module project is preparing for public launch as a multi-user portfolio risk
analysis platform with a freemium model (Free / Pro / Business tiers). It currently has
**zero legal documents** -- no Terms of Service, no Privacy Policy, no data handling
disclosures, no account deletion flow, and a LICENSE file conflict (root LICENSE says
proprietary, root `package.json` says MIT).

This platform handles sensitive financial data from multiple brokerage providers (Plaid,
SnapTrade, IBKR, Schwab), stores user identity via Google OAuth, persists portfolio
positions and transaction history in PostgreSQL/RDS, and sends financial data to third
parties (FMP for market data, Anthropic/Claude for AI features). Launching without legal
documents exposes the project to regulatory risk, provider policy violations (Plaid
requires end-user disclosures), and user trust issues.

---

## What Data Exists Today

### User Identity Data (PostgreSQL `users` table)

| Column | Type | Source |
|--------|------|--------|
| `email` | VARCHAR(255) | Google OAuth |
| `name` | VARCHAR(255) | Google OAuth |
| `google_user_id` | VARCHAR(255) | Google OAuth `sub` claim |
| `github_user_id` | VARCHAR(255) | Future provider |
| `apple_user_id` | VARCHAR(255) | Future provider |
| `auth_provider` | VARCHAR(50) | `google` (current default) |
| `tier` | VARCHAR(50) | `public` / `registered` / `paid` |
| `api_key_hash` | VARCHAR(255) | Programmatic access (future) |
| `created_at` / `updated_at` | TIMESTAMP | System |

### Session Data (PostgreSQL `user_sessions` table)

| Column | Type |
|--------|------|
| `session_id` | VARCHAR(255) PK |
| `user_id` | INTEGER FK |
| `expires_at` | TIMESTAMP |
| `last_accessed` | TIMESTAMP |

Session resolution returns: `user_id`, `google_user_id`, `email`, `name`, `tier`
(see `app_platform/auth/stores.py` `PostgresSessionStore.get_session()`).

### Financial Data (PostgreSQL -- all scoped by `user_id`)

| Table | Key Data | Sensitivity |
|-------|----------|-------------|
| `portfolios` | Name, dates, type, active status | Low |
| `positions` | Ticker, quantity, currency, cost_basis, purchase_date, account_id, brokerage_name | HIGH -- real portfolio holdings |
| `accounts` | External account IDs, institution names, account types | HIGH -- identifies real brokerage accounts |
| `data_sources` | Provider, institution, sync timestamps | Medium |
| `provider_items` | Plaid/SnapTrade item IDs, institution names | HIGH -- provider linkage tokens |
| `risk_limits` | Volatility/concentration/factor limits | Low |
| `factor_proxies` | Per-ticker factor model configuration | Low |
| `scenarios` / `scenario_positions` | What-if scenarios | Low |
| `expected_returns` | Per-ticker return forecasts | Low |
| `target_allocations` | Asset class weight targets | Low |
| `user_preferences` | Risk tolerance, goals, constraints | Medium |
| `conversation_history` | AI chat topics, insights, action items | Medium |
| `portfolio_changes` | Audit trail of position changes | Medium |

### Transaction Store (PostgreSQL -- added 2026-03-03)

| Table | Key Data | Sensitivity |
|-------|----------|-------------|
| `ingestion_batches` | Provider, institution, fetch windows, diagnostics | Medium |
| `raw_transactions` | Full raw provider payloads (JSONB), dates, symbols | HIGH |
| `plaid_securities` | Security IDs, CUSIPs, ISINs, names, option contracts | HIGH |
| `normalized_transactions` | Symbol, quantity, price, trade type, account | HIGH |
| `income_events` | Dividend/interest amounts, symbols, ex-dates | HIGH |
| `flow_events` | Cash transfers, deposits, withdrawals | HIGH |

### Brokerage Provider Integrations

From `providers/routing.py`:

| Provider | Position Data | Transaction Data | Credential Type |
|----------|--------------|-----------------|-----------------|
| **Plaid** | Yes (`plaid`) | Yes (`plaid`) | Access token via Plaid Link OAuth |
| **SnapTrade** | Yes (`snaptrade`) | Yes (`snaptrade`) | OAuth via SnapTrade |
| **IBKR** | Yes (`ibkr`) | Yes (`ibkr_flex`, `ibkr_statement`) | IB Gateway API + Flex Query tokens |
| **Schwab** | Yes (`schwab`) | Yes (`schwab`, `schwab_csv`) | OAuth token file |

### Third-Party Data Sharing

| Third Party | Data Sent | Purpose |
|-------------|-----------|---------|
| **FMP** (Financial Modeling Prep) | Ticker symbols, date ranges | Market data, quotes, fundamentals, factor analysis |
| **Anthropic / Claude** | Portfolio context, user chat messages | AI agent responses, analysis |
| **Google** | OAuth token exchange | Authentication |
| **AWS** (hosting) | All data at rest | Infrastructure |

---

## 1. Terms of Service

### 1.1 Scope of Service

Define the platform as a portfolio risk analysis and visualization tool:
- Imports portfolio positions from brokerage providers or CSV upload
- Calculates risk metrics (VaR, factor exposures, concentration, drawdown)
- Runs scenario analysis (stress tests, Monte Carlo, what-if)
- Provides AI-assisted portfolio analysis via Claude
- Displays dashboards, charts, and reports
- Does NOT execute trades on behalf of users (IBKR trading is user-initiated)
- Does NOT custody or hold user funds

### 1.2 Eligibility

- Minimum age: 18 years
- Must have legal capacity to enter binding agreement
- One account per person
- Must be authorized to connect any brokerage accounts they link

### 1.3 Account Creation

- Google OAuth sign-in required (current sole auth provider)
- User agrees to provide accurate information
- User responsible for Google account security
- Account creation implies acceptance of ToS and Privacy Policy

### 1.4 Financial Data Disclaimer

**This is the most critical section for a portfolio analysis platform.**

```
[PRODUCT_NAME] IS NOT A REGISTERED INVESTMENT ADVISER, BROKER-DEALER,
OR FINANCIAL PLANNER. NOTHING IN THE SERVICE CONSTITUTES INVESTMENT
ADVICE, FINANCIAL ADVICE, TRADING ADVICE, OR ANY OTHER SORT OF ADVICE.

The Service provides analytical tools and informational displays based
on data imported from your brokerage accounts and third-party market
data providers. All analysis, risk scores, factor exposures, scenario
results, and AI-generated insights are for informational purposes only.

You should not make investment decisions based solely on information
from this Service. Consult a qualified financial professional.
```

Sections to cover:
- Risk metrics are statistical estimates, not predictions
- Factor analysis uses historical data and may not reflect future behavior
- Monte Carlo simulations model probability distributions, not guaranteed outcomes
- Optimization results are theoretical and assume frictionless markets
- Stress test scenarios are illustrative, not exhaustive
- AI-generated analysis may contain errors or hallucinations

### 1.5 Data Accuracy Limitations

- Brokerage data provided "as-is" from Plaid, SnapTrade, IBKR, Schwab
- Positions and balances may be delayed or stale
- Market data from FMP may be delayed (free tier) or contain errors
- Currency conversions use approximate FX rates
- Transaction history completeness depends on provider data windows
  (e.g., IBKR Flex query is limited to ~12-month lookback)
- CSV imports rely on automated parsing; errors possible
- Cost basis calculations are best-effort (FIFO); verify against broker statements

### 1.6 User Responsibilities

- Verify analysis results against official brokerage statements
- Maintain security of connected brokerage accounts
- Report unauthorized access immediately
- Do not use the platform for market manipulation or insider trading
- Comply with applicable securities laws
- Understand that risk analysis is not risk elimination

### 1.7 Intellectual Property

- Platform code, design, documentation owned by [COMPANY_NAME]
- User's financial data remains user's property at all times
- Open-source components licensed under their respective licenses
  (see License Resolution section below for the pending decision)
- User grants platform limited license to process their data for service delivery

### 1.8 Service Availability

- Free tier: No uptime commitment, best-effort availability
- Pro tier: Reasonable uptime target, no formal SLA
- Business tier: Defined SLA with uptime percentage and remedies
- Planned maintenance windows communicated via in-app notice
- Provider outages (Plaid, FMP, IBKR) outside platform's control

### 1.9 Subscription and Billing

Per the pricing model in `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`:

| Tier | Price | Billing | Features |
|------|-------|---------|----------|
| Free | $0 | N/A | Dashboard, CSV import, manual analysis tools, delayed data |
| Pro | $X/month | Monthly/Annual | AI agent, Plaid connection, real-time data, skills, memory |
| Business | $Y/month + implementation | Custom | Multi-user, custom integrations, SLA |

Must include:
- Auto-renewal disclosure (California ARL compliance)
- Cancellation method (must be as easy as signup)
- What happens on downgrade (retain access through billing period)
- Price change notice period (minimum 30 days)
- Refund policy

### 1.10 Termination and Suspension

**By platform:**
- Violation of terms
- Abuse of infrastructure / rate limits
- Legal requirement
- Extended inactivity (12+ months)
- Non-payment (Pro/Business)

**By user:**
- Delete account at any time via Settings
- Export data before deletion (CSV export of positions, transactions)
- See Account Deletion Flow (Section 4) for details

**Effect:**
- Access revoked immediately
- Data deleted per deletion flow
- Active subscription cancelled (no further charges)

### 1.11 Limitation of Liability

- Service provided "AS IS" and "AS AVAILABLE"
- No warranties express or implied (merchantability, fitness, non-infringement)
- Not liable for: incorrect risk calculations, stale market data, AI errors,
  brokerage data gaps, investment losses, missed opportunities
- Liability cap: greater of (a) 12 months of fees paid, or (b) $100
- No consequential, incidental, special, or punitive damages
- Carve-outs for gross negligence, willful misconduct, death/injury

### 1.12 Dispute Resolution

Recommended: Option C from finance-cli precedent:
1. Informal resolution attempt (30-day good-faith period)
2. Binding arbitration (JAMS or AAA) if informal resolution fails
3. Small claims court exception (either party can go to small claims)
4. Class action waiver
5. Governing law: state of LLC formation

### 1.13 Modification of Terms

- 30-day advance notice for material changes
- Notice via email and in-app banner
- Continued use after effective date = acceptance
- If user disagrees, must stop using service and delete account

---

## 2. Privacy Policy

### 2.1 Personal Data Collected

#### At Registration
- Google profile: name, email, profile picture URL
- Google `sub` identifier (stored as `google_user_id`)
- System-generated: user_id, tier, created_at

#### During Use
- Session data: session_id, login/logout timestamps, last_accessed, IP address
- User preferences: risk tolerance, goals, constraints
- Conversation history: AI chat topics, insights, action items
- Portfolio configuration: names, date ranges, account mappings

#### Financial Data (via provider connections)
- **Positions:** Ticker symbols, share quantities, currencies, cost basis,
  purchase dates, account identifiers, institution names
- **Transactions:** Trade type, symbol, quantity, price, date, settlement date,
  commissions, fees, broker-reported cost basis (raw JSONB payloads preserved)
- **Income events:** Dividends, interest, amounts, ex-dates, pay-dates
- **Flow events:** Cash transfers, deposits, withdrawals
- **Securities metadata:** CUSIPs, ISINs, security names, option contract details

#### Technical/Usage Data
- HTTP request logs: endpoint, timestamp, status code, response time
- API usage metrics: token counts for AI calls, provider sync counts
- Browser/device info from HTTP headers (not fingerprinted)
- Error logs with user_id context

### 2.2 How Data is Stored

- **Primary database:** PostgreSQL on AWS RDS (encrypted at rest via AES-256)
- **User isolation:** All tables keyed by `user_id` with `ON DELETE CASCADE`
- **Sessions:** PostgreSQL `user_sessions` table with expiration
- **Market data cache:** Local Parquet files (FMP price series), no PII
- **Secrets:** Provider tokens stored via environment variables / AWS Secrets Manager
- **Backups:** Automated RDS snapshots with tiered retention

### 2.3 Third-Party Data Sharing

| Third Party | Data Shared | Purpose | Their Privacy Policy |
|-------------|-------------|---------|---------------------|
| **Plaid** | Bank credentials entered into Plaid Link (never seen by us); we receive positions/transactions | Brokerage data aggregation | https://plaid.com/legal/#end-user-privacy-policy |
| **SnapTrade** | OAuth token exchange; we receive positions/transactions | Brokerage data aggregation | https://snaptrade.com/privacy |
| **IBKR** | API credentials provided by user; we receive positions/orders/market data | Direct broker connection | https://www.interactivebrokers.com/en/general/privacy.php |
| **FMP** | Ticker symbols, date ranges (no PII) | Market data, fundamentals, quotes | https://site.financialmodelingprep.com/privacy-policy |
| **Anthropic** | Portfolio context, user chat messages | AI-powered analysis and chat | https://www.anthropic.com/privacy |
| **Google** | OAuth token exchange | Authentication | https://policies.google.com/privacy |
| **AWS** | All data at rest (infrastructure) | Cloud hosting | https://aws.amazon.com/privacy/ |

**We do NOT:**
- Sell user data to third parties
- Share financial data for advertising or marketing
- Use user data for model training (Anthropic API tier)
- Share data between users

### 2.4 Data Retention

| Data Type | Retention | Basis |
|-----------|-----------|-------|
| Account information | Until account deletion | Service delivery |
| Financial positions/transactions | Until account deletion | Service delivery |
| AI conversation history | Until account deletion | Service delivery |
| User preferences | Until account deletion | Service delivery |
| Session records | Until expiration + cleanup | Security |
| Server access logs | 90 days, then deleted | Security/debugging |
| Error logs | 90 days, then deleted | Debugging |
| Aggregated analytics | Indefinite (anonymized, no PII) | Service improvement |
| Database backups | 7 days (daily), 30 days (weekly) | Disaster recovery |

### 2.5 User Rights

**All users:**
- **Access:** View all data via the dashboard; export positions/transactions as CSV
- **Correction:** Edit portfolio configuration, positions, preferences via UI
- **Deletion:** Delete account and all data via Settings (see Section 4)
- **Portability:** Export data in standard formats (CSV)
- **Disconnect:** Remove any individual provider connection at any time

**California residents (CCPA):**
- Right to know what personal information is collected
- Right to delete personal information
- Right to opt-out of sale (we do not sell data)
- Right to non-discrimination for exercising rights
- Note: CCPA thresholds ($26.625M revenue or 100K+ consumers) likely not met
  at launch, but rights are honored regardless

**EU residents (GDPR):**
- At launch: consider geo-blocking EU users to avoid GDPR transfer complexity
- If accepting EU users: legal basis is contract performance (Art. 6(1)(b)),
  with legitimate interests (Art. 6(1)(f)) for security/improvement
- Standard Contractual Clauses needed for US data storage
- Right to erasure, portability, restriction, objection all supported
  via the same deletion/export mechanisms

### 2.6 Cookie/Session Policy

| Cookie/Storage | Purpose | Type | Duration |
|----------------|---------|------|----------|
| `session_id` | Authentication | HttpOnly, Secure, SameSite=Lax | 7 days |
| Google OAuth state | Sign-in flow | Third-party (Google) | Session only |

No advertising cookies. No third-party analytics cookies. No cross-site tracking.

---

## 3. Data Handling Disclosures

### 3.1 Plaid End-User Disclosure

**Required by Plaid Developer Policy** -- must be shown to users BEFORE they open
Plaid Link.

Content must include:
- What data will be accessed (positions, transactions, balances)
- How data will be used (portfolio analysis, risk calculation, performance tracking)
- That Plaid is used as intermediary
- Link to platform's Privacy Policy
- Link to Plaid's End User Privacy Policy
- Explicit consent mechanism ("I agree" button or checkbox)

```
Connecting your brokerage account

[PRODUCT_NAME] uses Plaid to securely connect to your financial
institutions. By proceeding, you authorize Plaid to access the
following from your connected accounts:

- Portfolio positions (holdings, quantities, values)
- Transaction history (trades, dividends, transfers)
- Account balances (current and available)

Your brokerage login credentials are entered directly into Plaid's
secure interface. We never see or store your brokerage username or
password.

You can disconnect any account at any time from Settings, or manage
your connections directly at my.plaid.com.

By continuing, you agree to Plaid's End User Privacy Policy
(https://plaid.com/legal/#end-user-privacy-policy) and our Privacy
Policy ([PRIVACY_POLICY_URL]).

[Connect My Accounts]  [Learn More]
```

### 3.2 SnapTrade Data Handling

- SnapTrade OAuth flow -- user authorizes access via SnapTrade's interface
- We receive: positions, transactions, account metadata
- Data stored in PostgreSQL with user_id scoping
- User can disconnect via Settings at any time

### 3.3 IBKR Data Usage

- User provides IB Gateway API credentials or Flex Query token
- Credentials stored as environment variables (not in database)
- We access: positions, orders, market data, Flex Query reports
- IBKR Flex data window is ~12 months (hard constraint, cannot be extended)
- Live trading is user-initiated only; platform does not auto-execute

### 3.4 FMP Data Attribution

Per FMP terms, market data sourced from FMP must include attribution:
- Display "Data provided by Financial Modeling Prep" or similar
- Link to FMP where market data is displayed
- Market data may be delayed (free FMP tier: 15-minute delay)
- Historical data accuracy depends on FMP's data quality

---

## 4. Account Deletion Flow

### 4.1 User-Initiated Deletion

**Trigger:** User clicks "Delete Account" in Settings page

**Pre-deletion UI:**

```
Delete your account?

This will permanently delete:
- All your portfolio data (positions, transactions, performance history)
- All connected brokerage accounts (provider tokens will be revoked)
- Your AI conversation history and preferences
- Your risk settings, scenarios, and target allocations
- Your account and all associated settings

This action cannot be undone.

You can export your data first using the Export button above.

[Export Data First]  [Cancel]  [Delete My Account]
```

### 4.2 Deletion Procedure

**Step 1: Confirmation**
- Require user to type "DELETE" or their email to confirm
- Rate-limit the deletion endpoint

**Step 2: Revoke External Tokens**
- Revoke Plaid access tokens (call `/item/remove` on Plaid's API)
- Revoke SnapTrade connections
- Clear IBKR Flex query tokens
- Clear Schwab OAuth tokens
- Non-blocking: if a revocation fails, log and continue

**Step 3: Delete Financial Data (PostgreSQL CASCADE)**
All tables have `ON DELETE CASCADE` from `users(id)`, so deleting the user
record cascades to:
- `portfolios` -> `positions`, `portfolio_accounts`, `scenarios`,
  `scenario_positions`, `risk_limits`, `factor_proxies`, `factor_tracking`
- `accounts`, `data_sources`, `provider_items`
- `target_allocations`, `expected_returns`
- `user_preferences`, `conversation_history`
- `portfolio_changes` (audit trail)
- `ingestion_batches` -> `raw_transactions`, `normalized_transactions`,
  `income_events`, `flow_events`, `plaid_securities`
- `user_sessions`

**Step 4: Clear Session**
- Delete active session from session store
- Clear `session_id` cookie
- Return confirmation response

### 4.3 What Gets Retained

| Data | Retention | Reason |
|------|-----------|--------|
| Server access logs with user_id | 90 days | Security/debugging |
| Error logs with user_id | 90 days | Debugging |
| Database backups containing user data | Up to 30 days | Disaster recovery |
| Aggregated analytics (no PII) | Indefinite | Service improvement |

### 4.4 Grace Period Decision

**Recommended: 7-day soft-delete grace period**

- On deletion request: mark account as `pending_deletion`, revoke access
- During grace period: user can sign in and cancel deletion
- After 7 days: automated job executes hard delete (Steps 2-4)
- Rationale: prevents accidental deletion, industry standard practice

### 4.5 Technical Implementation

**API endpoint:** `DELETE /api/settings/account`

**Requirements:**
- Authenticated (valid session required)
- Confirmation token in request body (prevents CSRF)
- Rate limited (1 attempt per 5 minutes per user)
- Idempotent (second call on pending_deletion is a no-op)

**Frontend:**
- Settings page > "Delete Account" section
- Confirmation modal with destructive action styling
- "Export Data First" button prominently displayed
- Progress indicator during deletion

**Database migration:**
- Add `deletion_requested_at TIMESTAMP` and `deletion_scheduled_at TIMESTAMP`
  columns to `users` table
- Add `is_pending_deletion BOOLEAN DEFAULT FALSE` column
- Create scheduled job to process pending deletions after grace period

---

## 5. License Resolution

### 5.1 Current State (CONFLICT)

| Location | License Declared |
|----------|-----------------|
| `/LICENSE` | Proprietary -- "permission required for ANY use" |
| `/package.json` (root) | `"license": "MIT"` |
| `/frontend/packages/app-platform/package.json` | `"license": "SEE LICENSE IN LICENSE"` |
| `/frontend/package.json` | No license field |
| `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md` | Discusses MIT vs Apache 2.0 (undecided) |
| `PUBLIC_RELEASE_EXCLUSION_CHECKLIST.md` | Flags LICENSE as needing replacement |

The `LICENSE` file contains a strict proprietary license with personal contact
information (`hc@henrychien.com`). The root `package.json` contradicts this by
declaring MIT. This must be resolved before any public release.

### 5.2 Decision Framework

| Option | Pros | Cons |
|--------|------|------|
| **MIT** | Maximum adoption, simple, matches `package.json` | No patent protection, no copyleft |
| **Apache 2.0** | Patent grant, contributor protection, corporate-friendly | Slightly more complex than MIT |
| **AGPL** | Copyleft protects against SaaS free-riding | Scares away corporate adoption |
| **BSL (Business Source License)** | Source-available, converts to open after delay | Not OSI-approved, confusing |
| **Proprietary (current)** | Full control | Blocks open-source launch strategy entirely |

### 5.3 Recommendation

Per `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`, the stated vision is open-source infrastructure
with a hosted service as the business model. The recommended approach:

**Apache 2.0 for all packages** (portfolio-risk-engine, fmp-mcp, ibkr-mcp,
brokerage-connect, portfolio-mcp)

Rationale:
- Patent grant protects contributors and users
- Corporate-friendly (unlike AGPL)
- Standard for infrastructure/framework projects
- Aligns with "the code isn't the moat -- the expertise is" philosophy

**Actions required:**
1. Replace `/LICENSE` with Apache 2.0 text
2. Update `/package.json` `"license"` field to `"Apache-2.0"`
3. Update all sub-package `package.json` files to `"Apache-2.0"`
4. Add `SPDX-License-Identifier: Apache-2.0` headers to source files (optional but recommended)
5. Add `NOTICE` file with copyright attribution
6. Remove personal contact info from license file (email, GitHub)

---

## 6. Implementation Plan

### Phase 1: Document Drafting (Week 1-2)

| Task | Effort | Notes |
|------|--------|-------|
| Draft Terms of Service (all sections) | 1 day | Use finance-cli `DRAFT_D4_LEGAL.md` as template; adapt for portfolio/risk domain |
| Draft Privacy Policy (all sections) | 1 day | Audit all tables in `database/schema.sql` + transaction store migration |
| Draft Plaid disclosure text | 0.5 day | Follow Plaid Developer Policy requirements |
| Draft SnapTrade/IBKR/FMP disclosures | 0.5 day | Per provider requirements |
| Draft financial disclaimer templates | 0.5 day | Risk analysis, AI, data accuracy disclaimers |
| License decision + new LICENSE file | 0.5 day | Requires owner decision on open-source license |
| Fill all placeholders | 0.5 day | Company name, address, state, email, retention periods |
| **Total drafting** | **~5 days** | |

### Phase 2: Legal Review (Week 2-3)

| Task | Effort | Cost |
|------|--------|------|
| Attorney review of ToS | 1-2 hours | $500-$1,500 |
| Attorney review of Privacy Policy | 1-2 hours | $500-$1,500 |
| Plaid compliance review (internal) | 0.5 day | $0 |
| Finalize all documents | 0.5 day | $0 |
| **Total review** | **~2 days + attorney** | **$1,000-$3,000** |

### Phase 3: Technical Implementation (Week 3-4)

#### 3a. Frontend Legal Pages

| Task | Effort | Details |
|------|--------|---------|
| Create `/terms` route | 0.5 day | Static markdown rendering, accessible without auth |
| Create `/privacy` route | 0.5 day | Static markdown rendering, accessible without auth |
| Add footer links to all pages | 0.5 day | "Terms of Service" and "Privacy Policy" links in app footer |
| Add financial disclaimer to footer | 0.5 day | Persistent disclaimer text or link |
| Add AI disclaimer to chat interface | 0.5 day | Show on every AI-generated response |
| Add FMP attribution to market data views | 0.5 day | "Data provided by Financial Modeling Prep" |
| **Subtotal** | **~3 days** | |

#### 3b. Consent Collection

| Task | Effort | Details |
|------|--------|---------|
| Add ToS/PP checkbox to signup flow | 0.5 day | Required before account creation completes |
| Store consent version + timestamp | 0.5 day | New `user_consents` table: `user_id, document, version, accepted_at` |
| Re-consent flow for ToS updates | 1 day | Banner + modal when ToS version changes, block access until accepted |
| Plaid pre-link disclosure modal | 0.5 day | Show disclosure text + consent checkbox before Plaid Link opens |
| **Subtotal** | **~2.5 days** | |

**`user_consents` table schema:**

```sql
CREATE TABLE user_consents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_type VARCHAR(50) NOT NULL,  -- 'tos', 'privacy_policy', 'plaid_disclosure'
    document_version VARCHAR(20) NOT NULL,  -- 'v1.0', 'v1.1', etc.
    accepted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address VARCHAR(45),  -- For audit trail
    user_agent TEXT,  -- For audit trail
    UNIQUE(user_id, document_type, document_version)
);

CREATE INDEX idx_user_consents_user ON user_consents(user_id);
CREATE INDEX idx_user_consents_document ON user_consents(document_type, document_version);
```

#### 3c. Account Deletion Flow

| Task | Effort | Details |
|------|--------|---------|
| Add deletion columns to `users` table | 0.5 day | `deletion_requested_at`, `deletion_scheduled_at`, `is_pending_deletion` |
| Create `DELETE /api/settings/account` endpoint | 1 day | With confirmation, rate limiting, cascade |
| Implement provider token revocation | 1 day | Plaid `/item/remove`, SnapTrade disconnect, IBKR/Schwab cleanup |
| Frontend deletion UI (Settings page) | 1 day | Confirmation modal, export reminder, progress indicator |
| Scheduled job for grace period expiry | 0.5 day | Process pending deletions after 7 days |
| Post-deletion confirmation page | 0.5 day | Redirect after successful deletion |
| **Subtotal** | **~4.5 days** | |

#### 3d. License File Updates

| Task | Effort | Details |
|------|--------|---------|
| Replace `/LICENSE` with chosen license | 0.5 day | Remove proprietary text + personal info |
| Update all `package.json` license fields | 0.5 day | Root + all frontend packages |
| Add `NOTICE` file | 0.5 day | Copyright attribution per Apache 2.0 convention |
| **Subtotal** | **~1.5 days** | |

### Phase 4: ToS Version Management (Week 4-5)

| Task | Effort | Details |
|------|--------|---------|
| ToS/PP version tracking system | 1 day | Store document versions, detect when user's consent is stale |
| Re-consent middleware | 0.5 day | API middleware that checks consent version before serving requests |
| Admin tool to publish new ToS version | 0.5 day | Updates version, triggers re-consent flow for all users |
| **Subtotal** | **~2 days** | |

---

## 7. Disclaimer Templates

### 7.1 General Financial Disclaimer (App Footer)

```
IMPORTANT: [PRODUCT_NAME] is a portfolio risk analysis and visualization
tool, not a financial advisor, investment manager, or broker-dealer. The
information provided is for informational and analytical purposes only
and does not constitute investment, financial, tax, or legal advice.

You should consult qualified professionals before making investment
decisions based on information from this service. [COMPANY_NAME] is not
a registered investment adviser and is not licensed to provide financial
advice in any jurisdiction.
```

### 7.2 AI-Generated Content Disclaimer (Chat Interface)

```
This analysis was generated by artificial intelligence (Claude by
Anthropic) and may contain errors, inaccuracies, or outdated
information. AI-generated risk assessments, portfolio analysis, and
recommendations are provided as starting points for your review -- not
as definitive financial guidance.

Always verify AI-generated information against your official brokerage
statements and consult a qualified professional for investment decisions.
```

### 7.3 Risk Analysis Disclaimer (Risk/Scenario Pages)

```
Risk metrics, stress test results, and Monte Carlo simulations are
statistical estimates based on historical data and model assumptions.
Past performance and historical correlations do not guarantee future
results. Actual portfolio outcomes may differ materially from modeled
scenarios.
```

### 7.4 Data Accuracy Disclaimer (Dashboard / Reports)

```
Portfolio data shown here is imported from your brokerage accounts via
third-party data providers. This data may be delayed, incomplete, or
contain errors. Positions and balances may not reflect real-time values.

Always verify against your official brokerage account statements.
```

---

## 8. Open Decisions (Require Owner Input)

| # | Decision | Options | Deadline |
|---|----------|---------|----------|
| 1 | **License choice** | Apache 2.0 (recommended) / MIT / proprietary | Before public release |
| 2 | **Company entity** | Form LLC before accepting users | Before launch |
| 3 | **Company name** | "OpenClaw" per launch strategy? Or other? | Before legal docs |
| 4 | **Governing law state** | State of LLC formation | Before ToS finalization |
| 5 | **Deletion grace period** | 7-day soft-delete (recommended) vs immediate | Before implementation |
| 6 | **GDPR approach** | Geo-block EU (simpler) vs accept EU users (SCCs needed) | Before launch |
| 7 | **Contact email** | legal@domain, support@domain, privacy@domain | Before doc publication |
| 8 | **Liability cap amount** | $100 (standard for small scale) | Before ToS finalization |
| 9 | **Attorney budget** | $1,000-$3,000 for ToS/PP review | Before Phase 2 |
| 10 | **Cyber liability insurance** | $1,000-$3,000/year for fintech app | Before launch |

---

## 9. Regulatory Context

### 9.1 GLBA (Gramm-Leach-Bliley Act)

The platform likely qualifies as a "financial institution" under GLBA's broad
definition (data aggregators and consumer fintech apps are included). At launch
scale (<100 users), enforcement risk is minimal, but:

- Privacy Policy satisfies the Privacy Rule
- Security Implementation Plan (`docs/deployment/SECURITY_IMPLEMENTATION_PLAN.md`)
  constitutes an information security program for the Safeguards Rule
- Breach notification: plan for 30-day FTC notification if 500+ consumers affected

### 9.2 SEC / Investment Adviser Considerations

The platform is NOT an investment adviser because it:
- Does not provide personalized investment recommendations
- Does not manage portfolios on behalf of users
- Does not receive compensation for investment advice
- Provides tools and analysis, not advice

The financial disclaimers (Section 7) reinforce this distinction. The platform should
avoid language that implies advisory relationships (e.g., "we recommend" should be
"the analysis suggests").

### 9.3 State Privacy Laws

At launch scale, the platform falls below all state privacy law thresholds:
- CCPA: $26.6M revenue or 100K+ consumers
- Most other states: 100K+ consumers
- Include CCPA section in Privacy Policy anyway (costs nothing, signals maturity)

Revisit when approaching 10K users.

---

## 10. Estimated Total Effort

| Phase | Duration | Cost |
|-------|----------|------|
| Phase 1: Drafting | 5 days | $0 |
| Phase 2: Legal review | 2 days + attorney | $1,000-$3,000 |
| Phase 3: Implementation | ~11.5 days | $0 |
| Phase 4: Version management | 2 days | $0 |
| **Total** | **~20.5 dev days** | **$1,000-$3,000 attorney** |

Plus ongoing: LLC formation ($50-$150), cyber insurance ($1,000-$3,000/year).

---

## Related Documents

- `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md` -- Business model, pricing tiers, launch sequence
- `docs/deployment/SECURITY_IMPLEMENTATION_PLAN.md` -- Security gaps and remediation
- `docs/deployment/PUBLIC_RELEASE_EXCLUSION_CHECKLIST.md` -- Sensitive data to scrub
- `finance_cli/docs/planning/RECOMMENDATION_D4_LEGAL.md` -- Prior art (finance-cli legal recommendation)
- `finance_cli/docs/planning/DRAFT_D4_LEGAL.md` -- Prior art (finance-cli ToS/PP/deletion drafts)
- `finance_cli/docs/planning/RESEARCH_D4_LEGAL.md` -- Prior art (research spec)
- `database/schema.sql` -- Full database schema (what user data is stored)
- `database/migrations/20260303_add_transaction_store.sql` -- Transaction store tables
- `providers/routing.py` -- Brokerage provider integration list
- `app_platform/auth/stores.py` -- User and session store implementations
- `app_platform/auth/protocols.py` -- Auth protocol contracts
