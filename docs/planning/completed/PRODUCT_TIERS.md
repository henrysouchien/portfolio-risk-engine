# Product Tiers — Friction Ladder

**Status:** DRAFT | **Date:** 2026-03-10

Each tier removes friction and adds capability. The same codebase serves all tiers —
configuration (DB availability, auth mode, feature flags) determines what's active.

---

## Tiers

### Tier 1 — Open Source MCP (Free)

**Setup:** `pip install` + own FMP API key + CSV import
**Storage:** Filesystem (no DB)
**Auth:** None (single-user, local MCP)

- User adds `portfolio-mcp` to Claude Code
- Imports positions via CSV (`import_portfolio`)
- Full portfolio analysis: risk, optimization, what-if, factor analysis, etc.
- Agent creates normalizers for any brokerage format at runtime (Tier 1 local MCP only)
- FMP data via user's own API key (free tier: 100 calls/day)

**Config:** `DATABASE_URL` unset, `FMP_API_KEY` from user

### Tier 2 — Hosted Data MCP ($)

**Setup:** Register for API key, still local MCP
**Storage:** Filesystem (no DB)
**Auth:** API key for data access

- Same as Tier 1 but user doesn't need their own FMP key
- We provide data access (FMP, possibly other sources) behind our API key
- Cost covers data provider fees
- Still local MCP — no web app, no DB

**Config:** `DATABASE_URL` unset, hosted `FMP_API_KEY`

### Tier 3 — Web App + CSV (Free, limited)

**Setup:** Sign up (Google OAuth), upload CSV via web UI
**Storage:** DB (Postgres)
**Auth:** Google OAuth

- Browser-based — no local install
- CSV import via web upload (same `import_portfolio` pipeline)
- Limited tool access (analysis, no trading, no transactions)
- Token cap on agent interactions
- CSV data auto-skipped by safety guard when API connected; agent/UI suggests clearing stale CSV

**Config:** `DATABASE_URL` set, `AUTH_MODE=google` (or `AUTH_MODE=local` for single-user self-hosted), feature flags limit tools

### Tier 4 — Web App Full ($)

**Setup:** Sign up, connect brokerage (Plaid/SnapTrade/Schwab/IBKR)
**Storage:** DB (Postgres)
**Auth:** Google OAuth + brokerage OAuth

- All tools: analysis, trading, transactions, baskets, audit trail
- Live brokerage data (positions, transactions auto-sync)
- CSV import as fallback / supplement to API providers
- CSV cleared when API connected (graduation model, no dedup)
- Subscription covers infrastructure + data costs

**Config:** Full `.env`, all providers enabled

### Tier 5 — Web App + Agent ($$)

**Setup:** Full platform access
**Storage:** DB (Postgres)
**Auth:** Google OAuth + brokerage OAuth

- Everything in Tier 4
- Autonomous agent workflows (analyst-claude skills)
- Automated monitoring, rebalancing, research pipeline
- Token credits for agent compute
- Investment planning system integration

**Config:** Full `.env`, agent runner enabled, token billing

---

## Architecture Mapping

| Component | Tier 1-2 | Tier 3-5 |
|-----------|----------|----------|
| `is_db_available()` | `False` | `True` |
| Position storage | Filesystem JSON | DB (`positions` table) |
| CSV import | `import_portfolio` → JSON | `import_portfolio` → DB |
| CSV data lifecycle | Safety guard auto-skips; user clears via agent/tool | Safety guard auto-skips; user clears via UI or agent |
| Normalizers | `~/.risk_module/normalizers/` (agent-created) | Built-in only (no user dir scan — security) |
| Auth | None | Google OAuth |
| Brokerage providers | CSV only by default (live providers work if configured) | Plaid/SnapTrade/Schwab/IBKR |
| Trading | Not configured by default (works if IBKR Gateway configured) | Enabled (Tier 4+) |
| Transactions | `@require_db` error | Full store + sync |
| Agent workflows | Manual (user drives) | Automated (Tier 5) |

## Key Design Decisions

- **Same codebase, all tiers.** No separate "lite" vs "full" repos. Feature flags
  and `is_db_available()` gate everything.
- **CSV import is the universal entry point.** Works at every tier. The ingestion
  contract (`PositionRecord`, `NormalizeResult`) is the same regardless of storage.
- **Dual-path storage is the product architecture.** Not just a technical convenience —
  `is_db_available()` is the tier boundary between local MCP and hosted web app.
- **Agent-created normalizers are Tier 1 only.** Runtime normalizer authoring is
  local MCP only. Hosted tiers use reviewed built-in normalizers for security.
  Built-ins added by developers to `inputs/normalizers/` serve all tiers.
- **CSV → API graduation model.** Users start with CSV import, graduate to live API.
  Sequential states, not concurrent. No dedup needed — agent suggests clearing stale
  CSV data when API connects.

## Known Gaps

- **No tier detection mechanism.** "Feature flags limit tools" for Tier 3 is stated but no flags, frontend detection, or backend enforcement is defined yet. All web app users currently get the same tool access.
- **Transaction import is DB-only.** Tiers 1-2 can import positions via CSV but not transaction history. Realized performance, trading analysis, and tax harvest require Postgres (Tiers 3+).
- **`PROVIDER_CREDENTIALS` gaps.** Plaid/SnapTrade availability checks return True without credentials. Provider routing may advertise unavailable providers.
- **CSV→API safety guard uses exact brokerage_name matching.** Mismatched names between CSV and API may allow double-counting. Agent suggests clearing stale CSV data.

## Related Docs

- `PHASE_A_NO_INFRA_PLAN.md` — Implementation plan for Tier 1 (zero-infrastructure MCP)
- `POSITION_INGESTION_CONTRACT.md` — Ingestion schema shared across all tiers
- `ONBOARDING_FRICTION_AUDIT.md` — Original friction audit that motivated this tiering
