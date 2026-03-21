# Plaid vs SnapTrade: Brokerage Coverage Comparison

**Date:** 2026-03-20
**Purpose:** Evaluate aggregator coverage to inform provider routing strategy

---

## 1. Executive Summary

Plaid and SnapTrade serve fundamentally different roles. **Plaid** is a universal financial data aggregator covering 12,000+ institutions (banks, credit unions, brokerages) but provides **read-only** investment data with known quality limitations. **SnapTrade** is a brokerage-specialized aggregator covering ~25 institutions but offers **deeper investment data, OAuth-first connections, and trading capabilities**.

Our current routing strategy (SnapTrade preferred for brokerages, Plaid for banks) is directionally correct but needs refinement based on actual data quality and connectivity reliability.

---

## 2. Institution Coverage Matrix

### 2.1 Major US Brokerages

| Institution | SnapTrade | Plaid Investments | Our Direct API | Our Current Routing |
|---|---|---|---|---|
| Charles Schwab | Yes (OAuth, trading) | Yes (read-only) | Yes (`schwab`) | `["snaptrade", "plaid"]` + direct positions/txns |
| Fidelity | Yes (OAuth, read-only) | Problematic (see notes) | No | `["snaptrade", "plaid"]` |
| Vanguard | Yes (OAuth) | Yes (known issues) | No | `["snaptrade", "plaid"]` |
| E\*TRADE | Yes | Yes | No | `["snaptrade", "plaid"]` |
| Interactive Brokers | Yes (OAuth) | Yes | Yes (`ibkr` + `ibkr_flex`) | `["snaptrade", "plaid"]` + direct positions/txns |
| Merrill Edge / Lynch | No (not listed) | Yes | No | `["snaptrade", "plaid"]` |
| TD Ameritrade | No (merged into Schwab) | Yes (legacy) | No | `["snaptrade", "plaid"]` |
| Robinhood | Yes (OAuth, trading) | Yes | No | `["snaptrade", "plaid"]` |
| Webull | Yes (US + Canada) | Limited | No | `["snaptrade"]` |

### 2.2 Digital Investment Platforms

| Institution | SnapTrade | Plaid Investments | Our Current Routing |
|---|---|---|---|
| M1 Finance | No | Yes | `["plaid"]` |
| Betterment | No | Yes | `["plaid"]` |
| Wealthfront | No | Yes | `["plaid"]` |
| Public | Yes | Yes | Not configured |
| SoFi Invest | No | Yes | Not configured |
| Acorns | No | Yes | Not configured |
| Ally Invest | No | Yes | Not configured |
| Tastytrade | No | Unknown | Not configured |
| Firstrade | No | Unknown | Not configured |

### 2.3 SnapTrade-Only Brokerages (Not in Plaid or Niche)

| Institution | Region | Notes |
|---|---|---|
| Questrade | Canada | Major Canadian brokerage |
| Wealthsimple Trade | Canada | Canadian digital brokerage |
| DEGIRO | Europe | Major European discount broker |
| Trading212 | Europe/Global | Commission-free platform |
| Alpaca | US | API-first brokerage (+ Paper trading) |
| CommSec | Australia | Major Australian broker |
| Stake | Australia | Australian/US stock access |
| Chase (investments) | US | Self-directed investing via Chase |
| Wells Fargo (investments) | US | Advisors, WellsTrade |
| Empower | US | Retirement/advisory |
| Upstox | India | Indian market broker |
| Zerodha | India | Indian market broker |
| AJ Bell | UK | UK investment platform |
| BGL | Australia | SMSF/corporate |
| Bux | Europe | European neobroker |

### 2.4 Banks (Plaid Only, Not Investment-Relevant)

| Institution | Our Current Routing | Notes |
|---|---|---|
| Chase | `["plaid"]` | Banking only; investments would use SnapTrade |
| Bank of America | `["plaid"]` | Banking only; Merrill for investments |
| Wells Fargo | `["plaid"]` | Banking only; WellsTrade via SnapTrade |
| Citibank | `["plaid"]` | Banking only |
| US Bank | `["plaid"]` | Banking only |

---

## 3. Data Quality Comparison

### 3.1 Connection Method

| Dimension | SnapTrade | Plaid |
|---|---|---|
| **Primary method** | OAuth (brokerage-native) | Mixed (OAuth + credential relay) |
| **Screen scraping** | No | Transitioning away (1033 mandate) |
| **Credential handling** | Never touches credentials | Exchanges for tokens, discards |
| **Connection stability** | High (OAuth tokens refresh) | Variable (institution-dependent) |
| **Section 1033 readiness** | OAuth-native, minimal impact | Actively migrating, deadline July 2026+ |

### 3.2 Position & Holdings Data

| Dimension | SnapTrade | Plaid |
|---|---|---|
| **Position accuracy** | Direct from brokerage API | Aggregated, sometimes stale |
| **Real-time updates** | Yes (tier-dependent) | No (cached, refresh available) |
| **Cost basis** | Per-share, per-contract | Approximate (no fee inclusion, FDX limitation) |
| **Option positions** | Dedicated endpoint, contract-level | Via security metadata, less structured |
| **International tickers** | Yahoo Finance format (`.TO`, `.L`) | MIC-based, requires resolution |
| **Currency handling** | Position vs listing currency distinction | ISO currency code on transactions |

### 3.3 Transaction History

| Dimension | SnapTrade | Plaid |
|---|---|---|
| **History depth** | Full brokerage history (as far back as broker allows) | **24 months maximum** |
| **Transaction types** | BUY, SELL, DIVIDEND, REI, INTEREST, OPTIONEXPIRATION | buy, sell, cash, fee, dividend, interest, transfer |
| **Option activity** | `option_type` field (SELL_TO_OPEN, BUY_TO_CLOSE, etc.) | Inferred from subtype and name fields |
| **Short selling** | Via `option_type` mapping | Via subtype (`sell short`, `buy to cover`) |
| **Data normalization** | Structured activity model | Requires heavy parsing (see our normalizer) |
| **Instrument type codes** | Explicit (`cs`, `op`, `fut`, `bnd`, etc.) | Inferred from security metadata |

### 3.4 Known Data Quality Issues

**Plaid:**
- **Fidelity:** Actively blocked Plaid access. Plaid connections return stale/duplicate transactions. Fidelity prefers Akoya for data sharing. Our routing lists `["snaptrade", "plaid"]` but Plaid is unreliable here.
- **Vanguard:** Known issues with missing cash management transactions and inverted transaction signs (credits as debits). Connection availability windows reported as intermittent.
- **Cost basis:** Approximate only -- Plaid cannot include fees in cost basis calculation due to FDX schema limitations.
- **24-month transaction ceiling:** Hard limit. For realized performance analysis that spans multiple years, Plaid data alone is insufficient.

**SnapTrade:**
- **Fidelity:** Read-only (no trading). OAuth-based connection works.
- **Price freshness:** Depends on brokerage tier. Some provide real-time, others delayed. We supplement with FMP pricing regardless.
- **Smaller institution count:** Only ~25 brokerages vs Plaid's 12,000+. No coverage for robo-advisors (Betterment, Wealthfront, M1).

---

## 4. Our Current Provider Architecture

### 4.1 Provider Hierarchy

From `providers/routing_config.py`:

```
Priority: snaptrade (3) > plaid (2) > manual (1)
```

Direct providers override both aggregators when available:
- `POSITION_ROUTING`: Schwab direct for Schwab, IBKR direct for IBKR
- `TRANSACTION_ROUTING`: Schwab direct for Schwab, IBKR Flex for IBKR
- `TRADE_ROUTING`: IBKR Gateway for IBKR order execution

### 4.2 Five Provider Types

From `providers/routing.py`:

| Provider | Type | Purpose |
|---|---|---|
| `plaid` | Aggregator | Positions + transactions (read-only) |
| `snaptrade` | Aggregator | Positions + transactions + trading |
| `ibkr` | Direct | Positions + trading (IB Gateway) |
| `ibkr_flex` | Direct | Transactions (Flex Query reports) |
| `schwab` | Direct | Positions + transactions (Schwab API) |

### 4.3 Normalizer Implementations

Both aggregators have full normalizers in `providers/normalizers/`:
- `plaid.py` (PlaidNormalizer): Handles buy/sell/dividend/interest/fee mapping, option contract identity extraction from security metadata, bond face-value scaling, short sale detection
- `snaptrade.py` (SnapTradeNormalizer): Handles structured activity types, `option_type` field for short/cover detection, `snaptrade_type_code` for instrument classification, option expiration events

The SnapTrade normalizer benefits from more structured input data (explicit `type_code`, `option_type` fields), while the Plaid normalizer requires more inference from transaction names and security metadata.

---

## 5. Coverage Gap Analysis

### 5.1 Routing Configuration Issues

**Merrill Edge/Lynch** -- Currently routed `["snaptrade", "plaid"]` but SnapTrade does NOT support Merrill. Should be `["plaid"]` only, or requires a direct integration via Bank of America developer APIs.

**TD Ameritrade** -- Currently routed `["snaptrade", "plaid"]` but TD Ameritrade no longer exists as a separate entity (merged into Schwab). Should be deprecated and mapped to `charles_schwab`.

**Chase (investments)** -- Currently routed `["plaid"]` as a bank, but SnapTrade lists Chase as a supported brokerage. Chase's self-directed investing could use SnapTrade for investment data.

**Wells Fargo (investments)** -- Same situation as Chase. SnapTrade supports Wells Fargo for investment data; currently we only route to Plaid as a bank.

### 5.2 Missing Institutions

Popular US brokerages/platforms with NO coverage in our `INSTITUTION_PROVIDER_MAPPING`:
- **Public** -- Supported by both SnapTrade and Plaid
- **SoFi Invest** -- Supported by Plaid
- **Ally Invest** -- Supported by Plaid
- **Tastytrade** -- Would need investigation
- **Firstrade** -- Would need investigation

### 5.3 International Gaps

SnapTrade has better international coverage for investment-specific use cases:
- Canada: Questrade, Wealthsimple (SnapTrade only)
- Europe: DEGIRO, Trading212 (SnapTrade only)
- Australia: CommSec, Stake (SnapTrade only)

Plaid covers some international banks but its `Investments` product is limited to US and Canada.

---

## 6. Recommendations

### 6.1 Routing Strategy Fixes (Immediate)

1. **Fix Merrill routing**: Change from `["snaptrade", "plaid"]` to `["plaid"]`. SnapTrade does not support Merrill.

2. **Deprecate TD Ameritrade**: Map `td_ameritrade` to `charles_schwab` in slug aliases. The entity no longer exists independently.

3. **Add Chase/Wells Fargo investment routing**: For users connecting investment accounts at these institutions, route to SnapTrade as primary with Plaid fallback. Keep current `["plaid"]` routing for banking-only connections.

### 6.2 Provider Priority (Confirmed Correct)

For brokerages where both aggregators work, SnapTrade should remain primary because:
- OAuth-native connections (more stable, no screen scraping)
- Structured instrument type codes (less normalizer inference)
- Full transaction history (vs Plaid's 24-month cap)
- Option `type` fields (SELL_TO_OPEN, BUY_TO_CLOSE)
- Cost basis per share/contract (not approximate)
- Trading capability for future use

Plaid should remain the fallback for:
- Robo-advisors and digital platforms (Betterment, Wealthfront, M1, SoFi)
- Institutions where SnapTrade has no coverage
- Banking data (checking, savings, credit cards)

### 6.3 Direct Integration Priority

For institutions where aggregators have known quality issues, direct API integration provides the most reliable data:

| Priority | Institution | Reason | Status |
|---|---|---|---|
| Done | Interactive Brokers | Professional trading, options, futures | `ibkr` + `ibkr_flex` |
| Done | Charles Schwab | Major brokerage, direct API available | `schwab` |
| High | Fidelity | Plaid blocked, SnapTrade read-only, largest US brokerage | Not started |
| Medium | Vanguard | Plaid data quality issues, large AUM | Not started |
| Low | E\*TRADE | Both aggregators work adequately | Not started |

**Fidelity** is the highest-priority gap. It is the largest US retail brokerage by assets, Plaid connectivity is broken, and SnapTrade provides read-only access. A direct integration (if Fidelity's developer API is available) would provide the best data quality.

### 6.4 New Institution Onboarding

Institutions to add to `INSTITUTION_PROVIDER_MAPPING` based on US market share:

```
"public": ["snaptrade", "plaid"]       # Both aggregators support
"sofi": ["plaid"]                       # Plaid only
"ally_invest": ["plaid"]                # Plaid only
"tastytrade": ["plaid"]                 # Needs verification
"empower": ["snaptrade"]                # SnapTrade supported
```

### 6.5 Long-Term Architecture Considerations

1. **Section 1033 impact**: The CFPB open banking rule (compliance deadline July 2026+) will shift all providers toward standardized API access. Plaid is actively migrating away from screen scraping. This may improve Plaid's data quality for institutions like Vanguard over time, but the 24-month transaction history limit is a product constraint, not a scraping limitation.

2. **SnapTrade trading capability**: We currently use SnapTrade as read-only. Enabling trade execution through SnapTrade for supported brokerages (Schwab, Robinhood, E\*TRADE) could complement our IBKR Gateway direct trading.

3. **Cost considerations**: SnapTrade charges $1.50/user/month with no minimums. Plaid uses subscription + per-request pricing for investments. For a portfolio analysis app, SnapTrade's flat per-user pricing is simpler. Both have free tiers for development.

---

## 7. Summary Table: Recommended Routing

| Institution | Recommended Routing | Change Needed? |
|---|---|---|
| Charles Schwab | `schwab` direct (positions/txns), `["snaptrade", "plaid"]` fallback | No |
| Fidelity | `["snaptrade", "plaid"]` (SnapTrade primary) | No (direct API is future work) |
| Vanguard | `["snaptrade", "plaid"]` | No |
| E\*TRADE | `["snaptrade", "plaid"]` | No |
| Interactive Brokers | `ibkr`/`ibkr_flex` direct, `["snaptrade", "plaid"]` fallback | No |
| **Merrill Edge** | **`["plaid"]`** | **Yes -- remove snaptrade** |
| **TD Ameritrade** | **Alias to `charles_schwab`** | **Yes -- deprecate** |
| Robinhood | `["snaptrade", "plaid"]` | No |
| Webull | `["snaptrade"]` | No |
| M1 Finance | `["plaid"]` | No |
| Betterment | `["plaid"]` | No |
| Wealthfront | `["plaid"]` | No |
| Chase (bank) | `["plaid"]` | No |
| **Chase (investments)** | **`["snaptrade", "plaid"]`** | **Yes -- add investment path** |
| Bank of America (bank) | `["plaid"]` | No |
| Wells Fargo (bank) | `["plaid"]` | No |
| **Wells Fargo (investments)** | **`["snaptrade", "plaid"]`** | **Yes -- add investment path** |
| Citibank | `["plaid"]` | No |
| US Bank | `["plaid"]` | No |

---

## Sources

- [Plaid Institutions Coverage](https://plaid.com/docs/institutions/)
- [Plaid Investments Product](https://plaid.com/docs/investments/)
- [Plaid Investments API Reference](https://plaid.com/docs/api/products/investments/)
- [Plaid Institution Pages: Vanguard](https://plaid.com/institutions/vanguard/), [E\*TRADE](https://plaid.com/institutions/e-trade-financial/), [Merrill Lynch](https://plaid.com/institutions/merrill-lynch/), [IBKR](https://plaid.com/institutions/interactive-brokers-us/)
- [SnapTrade Brokerage Integrations](https://snaptrade.com/brokerage-integrations)
- [SnapTrade Documentation](https://docs.snaptrade.com/docs/integrations)
- [SnapTrade Brokerage Integrations (Notion)](https://snaptrade.notion.site/SnapTrade-Brokerage-Integrations-f83946a714a84c3caf599f6a945f0ead)
- [SnapTrade vs Plaid Comparison](https://snaptrade.com/snaptrade-vs-plaid)
- [SnapTrade Pricing](https://snaptrade.com/pricing)
- [Plaid vs Yodlee vs SnapTrade (SnapTrade blog)](https://snaptrade.com/blogs/plaid-vs-yodlee)
- [SnapTrade Schwab Integration](https://snaptrade.com/brokerage-integrations/schwab-api)
- [SnapTrade Fidelity Integration](https://snaptrade.com/brokerage-integrations/fidelity-api)
- [SnapTrade Vanguard Integration](https://snaptrade.com/brokerage-integrations/vanguard-api)
- [Plaid Section 1033 Guide](https://plaid.com/resources/compliance/section-1033-authorized-third-parties/)
- [RIABiz: Fidelity blocks Plaid screen scrapers](https://riabiz.com/a/2023/10/19/fidelity-just-dropped-the-hammer-on-screen-scrapers-to-cheers-but-some-firms-like-plaid-are-holdouts-and-the-cfpb-may-wield-the-final-gavel)
- [RIABiz: JPM/Fidelity/Schwab data access disputes](https://riabiz.com/a/2025/11/8/jp-morgan-hustles-plaid-for-a-deal-in-bitter-fight-over-free-data-with-wells-and-pnc-encouraged-while-fidelity-schwab-also-force-fintechs-to-pay-up-or-pound-sand-as-part-of-deeper-battle)
- [Fidelity confirms no Plaid use (X/Twitter)](https://x.com/Fidelity/status/2005631305740877942)
