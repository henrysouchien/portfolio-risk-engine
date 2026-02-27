# International Ticker Resolution Plan

## Problem Statement

Non-US securities (e.g., UK stocks on London Stock Exchange) have incorrect prices in the position monitor because:

1. **Plaid provides ticker without exchange suffix** (e.g., "AT" instead of "AT.L")
2. **FMP returns wrong/stale data** when queried with bare ticker
3. **Plaid's correct `institution_price` is overwritten** by FMP price in `_enrich_with_prices()`

## Investigation Findings (2026-01-31)

### Example: Ashtead Technology Holdings (AT)

| Field | Plaid Value | FMP Value | Correct Value |
|-------|-------------|-----------|---------------|
| ticker | "AT" | "AT" | "AT.L" |
| price | 4.035 GBP ✓ | 3.02 USD ✗ | 4.035 GBP |
| exchange_mic | None | N/A | "XLON" |

### Exchange MIC Code Availability

From fresh Plaid sync:
- `exchange_mic` values found: `XNYS`, `XNAS`, `OOTC`, `ARCX`, `None`
- **AT position: `exchange_mic` is `None`** - Plaid doesn't always provide this

### Security Identifiers (ISIN/CUSIP)

Plaid provides ISIN and CUSIP fields, but they **require a license verification process**
and are `null` by default for most customers. SEDOL is deprecated. Therefore:
- We cannot rely on ISIN/CUSIP for ticker resolution
- Must use name-based search as primary fallback when MIC is unavailable

### Data Flow Bug

```
1. Plaid API returns:
   - ticker: "AT"
   - institution_price: 4.035 (correct!)
   - market_identifier_code: None (not provided)

2. We save to database (price/value not persisted)

3. On load, _enrich_with_prices() calls:
   - latest_price("AT") → FMP returns 3.02 (wrong stock!)
   - Overwrites correct Plaid price
```

## Root Causes

1. **FMP ticker collision**: "AT" on FMP returns a delisted US stock, not London-listed Ashtead Technology
2. **No exchange-aware ticker mapping**: We don't append exchange suffixes for non-US stocks
3. **Price enrichment overwrites provider data**: Even when Plaid gives correct price, we replace it

## FMP Endpoint Analysis

| Endpoint | Data Quality | Best For |
|----------|--------------|----------|
| `stable/stock-list` | Sparse (48K symbols, names often missing) | Bulk download |
| `api/v3/search?query=` | Rich (name, currency, exchange) ✓ | **Ticker resolution** |
| `api/v3/profile/{symbol}` | Full details | Verification |

### Search Endpoint Example

Query: `api/v3/search?query=Ashtead+Technology+Holdings`

Response includes:
```json
{
  "symbol": "AT.L",
  "name": "Ashtead Technology Holdings Plc",
  "currency": "GBp",
  "stockExchange": "London Stock Exchange",
  "exchangeShortName": "LSE"
}
```

## Solution: Name-Based Resolution with Dual Ticker Storage

**Use FMP search endpoint to resolve provider ticker → FMP ticker, store both in DB**

### Configuration File

Exchange mappings are stored in a separate YAML config file for easy maintenance:

**File:** `exchange_mappings.yaml` (root directory, consistent with other YAML configs like `risk_limits_adjusted.yaml`)

```yaml
# Exchange MIC to FMP suffix mappings
# MIC codes: ISO-10383 standard (https://www.iso20022.org/market-identifier-codes)
# FMP suffixes: Used for international stock queries on Financial Modeling Prep

mic_to_fmp_suffix:
  # Europe
  XLON: ".L"    # London Stock Exchange
  XPAR: ".PA"   # Euronext Paris
  XETR: ".DE"   # Deutsche Börse Xetra
  XAMS: ".AS"   # Euronext Amsterdam
  XBRU: ".BR"   # Euronext Brussels
  XMIL: ".MI"   # Borsa Italiana (Milan)
  XMAD: ".MC"   # Bolsa de Madrid
  XSWX: ".SW"   # SIX Swiss Exchange

  # Americas (non-US)
  XTSE: ".TO"   # Toronto Stock Exchange
  XTSX: ".V"    # TSX Venture Exchange
  XMEX: ".MX"   # Bolsa Mexicana de Valores
  XBSP: ".SA"   # B3 (Brazil)

  # Asia-Pacific
  XHKG: ".HK"   # Hong Kong Stock Exchange
  XTKS: ".T"    # Tokyo Stock Exchange
  XASX: ".AX"   # Australian Securities Exchange
  XSES: ".SI"   # Singapore Exchange
  XKRX: ".KS"   # Korea Exchange
  XBOM: ".BO"   # BSE India (Bombay)
  XNSE: ".NS"   # NSE India

  # Add more as needed...

# US exchange MIC codes - only skip resolution if exchange_mic is one of these
us_exchange_mics:
  - XNYS  # New York Stock Exchange
  - XNAS  # NASDAQ
  - XASE  # NYSE American (formerly AMEX)
  - ARCX  # NYSE Arca
  - BATS  # BATS Global Markets
  - IEXG  # IEX
  - OOTC  # OTC Markets

# Minor currency mappings
# FMP uses lowercase suffix to indicate minor units (GBp = pence, ZAc = cents)
# Keys preserve original case for detection; values are (base_currency, divisor)
#
# IMPORTANT: Check ORIGINAL FMP currency string (case-sensitive) to detect minor units
# "GBp" (pence) needs conversion, "GBP" (pounds) does not
#
minor_currencies:
  GBp:                    # British pence
    base_currency: GBP
    divisor: 100
  GBX:                    # Alternative pence code
    base_currency: GBP
    divisor: 100
  ZAc:                    # South African cents
    base_currency: ZAR
    divisor: 100
  ILA:                    # Israeli agorot
    base_currency: ILS
    divisor: 100

# Currency normalization for MATCHING (case-insensitive)
# Used when comparing provider currency to FMP search results
# After uppercasing both sides, these map to base currency
# NOTE: Minor unit codes (after uppercase) must map to base currency for matching
currency_aliases:
  GBX: GBP   # Alternative pence code → pounds
  ZAC: ZAR   # ZAc (cents) uppercased → rand
  ILA: ILS   # Agorot uppercased → shekels
  # GBP stays as GBP (GBp.upper() = GBP, no alias needed)

# FMP exchange short names for disambiguation
mic_to_exchange_short_name:
  XLON: LSE
  XPAR: EURONEXT
  XETR: XETRA
  XTSE: TSX
  XHKG: HKSE
  XTKS: TSE
  XASX: ASX
```

### Currency & Price Unit Handling

**Problem:** FMP returns prices in minor currency units for some exchanges (e.g., GBp = pence, not pounds).

**Solution:** Two separate normalizations:

1. **For currency MATCHING** (in resolver): Use `currency_aliases` to treat equivalent currencies
   the same (e.g., GBX → GBP) so search results match provider currency.

2. **For PRICE normalization** (when fetching quotes): Use `minor_currencies` config to detect
   minor units (GBp, ZAc) and convert to base currency (divide by 100).

```python
def normalize_fmp_price(price: float, currency: str) -> tuple[float, str]:
    """Convert FMP price from minor to base currency if needed.

    Loads minor_currencies config from exchange_mappings.yaml (single source of truth).

    FMP uses specific codes for minor units (some mixed-case, some all-caps):
    - "GBp" = pence, "GBX" = pence (divide by 100 to get pounds)
    - "GBP" = pounds (no conversion)
    - "ZAc" = cents (divide by 100 to get rand)

    ASSUMPTION: FMP consistently uses these exact codes. If FMP changes their
    casing convention (e.g., returns "gbp" or "gbx" lowercase), minor unit
    detection will fail and prices will be 100x too high. A warning is logged
    when we see a lowercase variant of a known minor currency key.

    Args:
        price: Raw price from FMP (may be None)
        currency: Currency code from FMP (e.g., "GBp", "ZAc", "USD", or None)

    Returns:
        (normalized_price, base_currency): Price in base units and normalized currency code
    """
    if price is None:
        return None, currency or 'USD'

    currency = currency or 'USD'  # Default if None

    # Load from config (single source of truth)
    config = load_exchange_mappings()
    minor_currencies = config.get('minor_currencies', {})

    # CASE-SENSITIVE exact match against config keys
    # FMP distinguishes minor vs base by case: "GBp" (pence) vs "GBP" (pounds)
    # Using case-insensitive lookup would incorrectly divide GBP by 100
    if currency in minor_currencies:
        entry = minor_currencies[currency]
        base_currency = entry['base_currency']
        divisor = entry['divisor']
        return price / divisor, base_currency

    # Warn if we see a lowercase variant of a known minor currency key
    # This catches: "gbp", "gbx", "zac", "ila" when we expect "GBp", "GBX", "ZAc", "ILA"
    # Check: has lowercase letters AND uppercase matches a known minor key
    minor_keys_upper = {k.upper() for k in minor_currencies.keys()}
    if currency != currency.upper() and currency.upper() in minor_keys_upper:
        log.warning(
            f"Currency {currency!r} looks like a casing variant of minor unit key - "
            f"expected exact case match. Verify if minor unit conversion was skipped."
        )

    # Not a minor currency - return as-is (uppercase for consistency)
    return price, currency.upper()

# Example:
# normalize_fmp_price(403.5, "GBp") → (4.035, "GBP")  # pence → pounds
# normalize_fmp_price(403.5, "GBP") → (403.5, "GBP")  # already pounds, no conversion
# normalize_fmp_price(150.0, "USD") → (150.0, "USD")
# normalize_fmp_price(100.0, None) → (100.0, "USD")
```

**Integration point:** The current `latest_price()` in `run_portfolio_risk.py` returns only a scalar price.

**Chosen approach:** Create new `fetch_fmp_quote_with_currency()` in `utils/ticker_resolver.py`
that returns `(price, currency)`. This avoids breaking existing code that uses `latest_price()`.

All price enrichment for positions should go through `_enrich_with_prices()` which will
use the new helper with currency normalization:

```python
# In utils/ticker_resolver.py (canonical location for all resolution helpers):
def fetch_fmp_quote_with_currency(symbol: str) -> tuple[float | None, str | None]:
    """Fetch FMP quote and return (price, currency).

    Uses /api/v3/quote/{symbol} endpoint which returns currency field.

    Returns:
        (price, currency) on success
        (None, None) on error or empty response
    """
    try:
        url = f"{BASE_URL}/api/v3/quote/{symbol}?apikey={FMP_API_KEY}"
        resp = requests.get(url, timeout=10)  # 10 second timeout
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0].get('price'), data[0].get('currency', 'USD')
        return None, None
    except requests.RequestException as e:
        log.warning(f"FMP quote fetch failed for {symbol}: {e}")
        return None, None

# In services/position_service.py _enrich_with_prices():
def _enrich_with_prices(self, df: pd.DataFrame) -> pd.DataFrame:
    for idx, row in df.iterrows():
        fmp_symbol = row.get('fmp_ticker') or row['ticker']
        raw_price, fmp_currency = fetch_fmp_quote_with_currency(fmp_symbol)
        if raw_price is not None:
            price, _ = normalize_fmp_price(raw_price, fmp_currency)
            df.at[idx, 'price'] = price
        # ...
```

**Note:** The existing `latest_price()` can continue to work for US stocks where currency
normalization isn't needed. The new helper is specifically for international stocks.

### Resolver Implementation

```python
import yaml
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def load_exchange_mappings():
    """Load exchange mappings from config file (cached)."""
    config_path = Path(__file__).parent.parent / "exchange_mappings.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)

def normalize_currency(currency: str) -> str | None:
    """Normalize currency code (e.g., GBp → GBP, GBX → GBP). Case-insensitive.

    Args:
        currency: Currency code (may be None)

    Returns:
        Normalized uppercase currency code, or None if input is None/empty.
        Returning None allows caller to decide whether to skip currency filtering.
    """
    if not currency:
        return None  # Let caller decide how to handle missing currency

    config = load_exchange_mappings()
    currency_aliases = config.get('currency_aliases', {})  # e.g., GBX → GBP
    # Normalize to uppercase, then check for alias
    currency_upper = currency.upper()
    return currency_aliases.get(currency_upper, currency_upper)

import re

# Corporate suffixes to strip for name comparison
CORPORATE_SUFFIXES = r'\b(Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited|Plc\.?|PLC|LLC|LP|LLP|Co\.?|Company|Group|Holdings?|SA|AG|NV|SE)\b'

def normalize_company_name(name: str) -> str:
    """Normalize company name for fuzzy matching.

    Strips corporate suffixes, punctuation, and extra whitespace.
    Example: "Ashtead Technology Holdings Plc" → "ashtead technology"
    """
    if not name:
        return ""
    # Lowercase
    name = name.lower()
    # Remove corporate suffixes
    name = re.sub(CORPORATE_SUFFIXES, '', name, flags=re.IGNORECASE)
    # Remove punctuation
    name = re.sub(r'[^\w\s]', '', name)
    # Collapse whitespace
    name = ' '.join(name.split())
    return name.strip()

def resolve_fmp_ticker(
    ticker: str,
    company_name: str,
    currency: str,
    exchange_mic: str = None
) -> str:
    """
    Resolve provider ticker to FMP-compatible ticker.

    Strategy:
    1. If exchange_mic indicates US exchange, return ticker as-is
    2. If exchange_mic available and maps to non-US suffix, append suffix
    3. If MIC is missing/unknown, search FMP by name + currency (regardless of currency)
    4. Cache results to avoid repeated API calls

    NOTE: We do NOT shortcut on USD currency alone, because ADRs and some
    non-US listings trade in USD. We only skip resolution when exchange_mic
    explicitly indicates a US venue. This means USD positions without MIC
    will still go through name-based search.
    """
    config = load_exchange_mappings()
    us_mics = set(config.get('us_exchange_mics', []))
    mic_to_suffix = config.get('mic_to_fmp_suffix', {})
    mic_to_exchange = config.get('mic_to_exchange_short_name', {})

    # 1. US exchange confirmed by MIC - no translation needed
    if exchange_mic and exchange_mic in us_mics:
        return ticker

    # 2. Non-US exchange with known MIC - append suffix
    if exchange_mic and exchange_mic in mic_to_suffix:
        return ticker + mic_to_suffix[exchange_mic]

    # 3. No MIC or unknown MIC - search FMP by company name
    #    Apply multiple disambiguation filters to reduce false matches
    #    NOTE: If company_name is missing, we skip search and fall back to raw ticker.
    #    Ticker-only search is too ambiguous (e.g., "AT" returns 10000+ results).
    if company_name:
        results = fmp_search(company_name)
        currency_norm = normalize_currency(currency)  # May be None if provider currency missing
        expected_exchange = mic_to_exchange.get(exchange_mic) if exchange_mic else None

        # Score candidates for best match
        candidates = []
        for r in results:
            fmp_currency = normalize_currency(r.get('currency', ''))
            fmp_exchange = r.get('exchangeShortName', '')
            fmp_symbol = r.get('symbol', '')
            fmp_name = r.get('name', '')

            # Filter by currency if known; skip filter if provider currency is missing
            # (avoids defaulting to USD and missing non-USD listings)
            if currency_norm is not None and fmp_currency != currency_norm:
                continue

            # If we have exchange hint, must match exchange
            if expected_exchange and fmp_exchange != expected_exchange:
                continue

            # Score the match for disambiguation
            score = 0

            # Prefer exact name match (case-insensitive)
            if fmp_name.lower() == company_name.lower():
                score += 100
            # Also check normalized name (strip corporate suffixes)
            elif normalize_company_name(fmp_name) == normalize_company_name(company_name):
                score += 80  # Strong match but not exact

            # Prefer symbol containing provider ticker (e.g., "AT" in "AT.L")
            # Handle share class suffixes (BRK.B) vs exchange suffixes (AT.L):
            # - Exchange suffixes are typically 1-2 chars after dot (L, PA, TO)
            # - Share classes are typically single letter (A, B)
            # For safety, compare full ticker if it already has a dot
            if '.' in ticker:
                # Provider ticker has dot (e.g., BRK.B) - compare as-is
                if fmp_symbol.upper() == ticker.upper():
                    score += 50
            else:
                # Provider ticker has no dot - extract base for comparison
                symbol_base = fmp_symbol.split('.')[0].upper()
                if symbol_base == ticker.upper():
                    score += 50

            # Prefer shorter symbols (less likely to be a different company)
            score -= len(fmp_symbol)

            candidates.append((score, r))

        # Return best match if we have candidates
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_match = candidates[0]

            # Low-confidence guardrail: if score is below threshold,
            # optionally verify via profile endpoint before accepting
            MIN_CONFIDENCE_SCORE = 30  # Adjust based on testing
            if best_score < MIN_CONFIDENCE_SCORE:
                # Log warning for manual review, but still return match
                # Future enhancement: call /api/v3/profile/{symbol} to verify
                log.warning(
                    f"Low confidence match for {ticker}: {best_match['symbol']} "
                    f"(score={best_score}). Consider manual verification."
                )

            return best_match['symbol']

    # 4. Fallback - return original ticker
    #    This happens when:
    #    - company_name is missing (can't do name search; ticker search too ambiguous)
    #    - Name search returned no currency-matched results
    #    WARNING: May cause wrong FMP data for unresolved international stocks
    return ticker
```

**Future guardrail:** For low-confidence matches (score < threshold), consider calling
`/api/v3/profile/{symbol}` to verify the company description matches before accepting.
This adds latency but reduces false positives for ambiguous cases.

### Cache Strategy

To avoid repeated FMP API calls, implement a resolution cache:

```python
# Cache configuration
RESOLUTION_CACHE_TTL = 86400 * 7  # 7 days - ticker mappings rarely change
NEGATIVE_CACHE_TTL = 86400        # 1 day for "no match" results (retry sooner)
# NOTE: Do NOT cache FMP errors (network, rate-limit) - retry immediately

# Cache key format: "{ticker}:{currency}:{exchange_mic or 'none'}"
# Example: "AT:GBP:none" or "VOD:GBP:XLON"

# Cache entry schema:
#   status: str          - "resolved" | "no_match"
#   fmp_ticker: str|null - resolved ticker or null for no_match
#   resolved_at: int     - Unix epoch seconds (NOT ISO string) for TTL comparison
#
# Cache entry structure - distinguish result types:
# {
#   "AT:GBP:none": {
#       "status": "resolved",      # "resolved" | "no_match" | (don't cache errors)
#       "fmp_ticker": "AT.L",
#       "resolved_at": 1738339200  # epoch seconds
#   },
#   "AAPL:USD:XNAS": {
#       "status": "resolved",
#       "fmp_ticker": "AAPL",      # Same as input (US exchange)
#       "resolved_at": 1738339200  # epoch seconds
#   },
#   "UNKNOWN:EUR:none": {
#       "status": "no_match",      # Search returned results but none matched
#       "fmp_ticker": null,
#       "resolved_at": 1738339200  # epoch seconds
#   }
#   # FMP errors (network, rate-limit, 500) are NOT cached - retry immediately
# }

def get_cached_resolution(cache_key: str) -> Optional[str]:
    """Get cached resolution, respecting TTL by status."""
    entry = cache.get(cache_key)
    if not entry:
        return None

    # resolved_at stored as epoch seconds (int) for easy TTL comparison
    age_seconds = int(time.time()) - entry['resolved_at']
    ttl = RESOLUTION_CACHE_TTL if entry['status'] == 'resolved' else NEGATIVE_CACHE_TTL

    if age_seconds > ttl:
        return None  # Expired

    return entry.get('fmp_ticker')  # May be None for no_match

# Cache storage format (use epoch seconds, not ISO strings):
# {
#   "AT:GBP:none": {
#       "status": "resolved",
#       "fmp_ticker": "AT.L",
#       "resolved_at": 1738339200  # epoch seconds
#   }
# }
```

### Integration Point

The resolver should be called when positions are first ingested from Plaid/SnapTrade,
storing the resolved `fmp_ticker` alongside the provider `ticker`. This way:
- All downstream FMP queries use the correct ticker
- Resolution happens once at sync time, not on every query
- Original provider ticker is preserved for reference

### Dual Ticker Storage (Why Two Fields?)

**Problem:** Sync reconciliation uses `(account_id, ticker, currency)` to match incoming
provider data with existing DB rows for upsert operations.

If we only stored the resolved FMP ticker:
- Plaid sends `ticker: "AT"` on next sync
- DB has `ticker: "AT.L"`
- They don't match → creates duplicate rows or orphans old data

**Solution:** Keep both fields:

| Field | Purpose | Example |
|-------|---------|---------|
| `ticker` | Original from provider, used for sync reconciliation | "AT" |
| `fmp_ticker` | Resolved for FMP queries (prices, historical data, risk) | "AT.L" |

**Fallback logic:** When resolution isn't needed or fails:
```python
# In resolve_fmp_ticker():
# - US exchange (confirmed by MIC): fmp_ticker = ticker (no resolution needed)
# - Non-US exchange with known MIC: fmp_ticker = ticker + suffix
# - Name search match: fmp_ticker = matched FMP symbol
# - Resolution fails: fmp_ticker = ticker (fallback, may cause issues for international)

# IMPORTANT: We do NOT shortcut on USD currency alone, because ADRs and
# some non-US listings trade in USD. Only skip when exchange_mic confirms US venue.

# In FMP query functions:
fmp_symbol = row.get('fmp_ticker') or row['ticker']  # NULL-safe fallback
```

## Files Changed

### Already Modified (exchange_mic extraction)
- `plaid_loader.py` - Added `exchange_mic` from `market_identifier_code`
- `snaptrade_loader.py` - Added `exchange_mic` from `exchange.mic_code`

### To Be Created (ticker resolution)
- `exchange_mappings.yaml` - Exchange config in root directory (consistent with `risk_limits_adjusted.yaml`)
  - `mic_to_fmp_suffix` - MIC → FMP suffix mappings
  - `us_exchange_mics` - US exchange MIC list (for shortcut logic)
  - `minor_currencies` - Minor currency detection (GBp → GBP with divisor 100)
  - `currency_aliases` - Currency aliases for matching (GBX → GBP)
  - `mic_to_exchange_short_name` - MIC → FMP exchange short name map
- `utils/ticker_resolver.py` - New module with:
  - `resolve_fmp_ticker()` function
  - `normalize_currency()` helper
  - `normalize_fmp_price()` helper
  - `normalize_company_name()` helper (strips "Plc", "Inc", etc. for fuzzy matching)
  - `fetch_fmp_quote_with_currency()` helper (returns price + currency for normalization)
  - Resolution cache layer (epoch timestamps, status field for error vs no-match)
- `database/migrations/YYYYMMDD_add_fmp_ticker.sql` - Migration to add column
- `scripts/backfill_fmp_tickers.py` - One-time backfill for existing non-USD positions

### To Be Modified (integration)
- `plaid_loader.py` - Call resolver during position normalization, populate `fmp_ticker`
- `snaptrade_loader.py` - Call resolver during position normalization, populate `fmp_ticker`
- `services/position_service.py` - Update `_enrich_with_prices()` to:
  - Use `fmp_ticker` field for FMP queries
  - Call `fetch_fmp_quote_with_currency()` from `utils/ticker_resolver.py`
  - Apply `normalize_fmp_price()` for minor currency conversion
- `inputs/database_client.py` - Add `fmp_ticker` to INSERT/SELECT statements
- `database/schema.sql` - Add `fmp_ticker` column definition
- `run_portfolio_risk.py` - Existing `latest_price()` can remain for US-only paths; international
  positions will use the new normalized price from `_enrich_with_prices()`

### Database Schema

#### Migration: Add `fmp_ticker` Column

**File:** `database/migrations/YYYYMMDD_add_fmp_ticker.sql`

```sql
-- Add fmp_ticker column for FMP-compatible ticker symbols
-- Original ticker preserved for provider sync reconciliation

ALTER TABLE positions
ADD COLUMN fmp_ticker VARCHAR(100);

-- Comment explaining the field
COMMENT ON COLUMN positions.fmp_ticker IS
    'FMP-compatible ticker (e.g., "AT.L" for London). NULL falls back to ticker column.';

-- Backfill Phase 1: Set fmp_ticker = ticker for positions on confirmed US exchanges
-- These don't need resolution
UPDATE positions
SET fmp_ticker = ticker
WHERE fmp_ticker IS NULL
  AND exchange_mic IN ('XNYS', 'XNAS', 'XASE', 'ARCX', 'BATS', 'IEXG', 'OOTC');

-- Backfill Phase 2: USD positions without exchange_mic
-- OPTION A (Conservative): Leave fmp_ticker NULL, run resolver script after migration
-- This ensures ADRs get resolved correctly instead of assuming US stock
-- OPTION B (Faster): Set fmp_ticker = ticker, accept ADRs may be wrong until next sync

-- Using OPTION A (recommended) - these will be handled by backfill script:
-- UPDATE positions SET fmp_ticker = ticker
-- WHERE fmp_ticker IS NULL AND currency = 'USD' AND exchange_mic IS NULL;

-- Index for FMP queries (optional, if we query by fmp_ticker directly)
-- CREATE INDEX idx_positions_fmp_ticker ON positions(fmp_ticker);
```

### Backfill Script for Unresolved Positions

After migration, positions with `fmp_ticker = NULL` need resolution. This includes:
- Non-USD positions (definitely need resolution)
- USD positions without exchange_mic (may be ADRs, need resolution attempt)

**Run one-time backfill script** after migration:

```python
def backfill_fmp_tickers():
    """One-time backfill for positions needing FMP ticker resolution."""
    # Query ALL positions with NULL fmp_ticker (non-USD and USD/no-MIC)
    positions = db.query("""
        SELECT id, ticker, name, currency, exchange_mic
        FROM positions
        WHERE fmp_ticker IS NULL
    """)

    resolved = 0
    failed = 0
    for pos in positions:
        try:
            fmp_ticker = resolve_fmp_ticker(
                ticker=pos['ticker'],
                company_name=pos['name'],
                currency=pos['currency'],
                exchange_mic=pos['exchange_mic']
            )
            db.execute("""
                UPDATE positions SET fmp_ticker = %s WHERE id = %s
            """, (fmp_ticker, pos['id']))
            resolved += 1
        except Exception as e:
            # Log but continue - don't block on individual failures
            log.warning(f"Failed to resolve {pos['ticker']}: {e}")
            failed += 1

    log.info(f"Backfill complete: {resolved} resolved, {failed} failed")
```

**Deployment order:**
1. Run migration (adds column, backfills confirmed US exchange positions)
2. Run backfill script (resolves remaining NULL positions)
3. Verify with spot checks on known international/ADR positions

#### Schema Update

**File:** `database/schema.sql` - Add to positions table:

```sql
fmp_ticker VARCHAR(100),           -- FMP-compatible ticker (NULL falls back to ticker)
```

#### Code Changes

**File:** `inputs/database_client.py` - Update INSERT statements:

```python
INSERT INTO positions
(portfolio_id, user_id, ticker, fmp_ticker, quantity, currency, type,
 account_id, cost_basis, position_source, name, brokerage_name, account_name)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
```

**File:** `services/position_service.py` - Update FMP queries:

```python
def _enrich_with_prices(self, df: pd.DataFrame) -> pd.DataFrame:
    for idx, row in df.iterrows():
        # Use fmp_ticker if available, fallback to ticker
        fmp_symbol = row.get('fmp_ticker') or row['ticker']

        # Use new helper that returns currency for normalization
        raw_price, fmp_currency = fetch_fmp_quote_with_currency(fmp_symbol)
        if raw_price is not None:
            # Normalize minor currencies (GBp → GBP, divide by 100)
            price, _ = normalize_fmp_price(raw_price, fmp_currency)
            df.at[idx, 'price'] = price
        # ...
```

**Note:** The existing `latest_price()` can remain for backward compatibility with
US-only code paths, but `_enrich_with_prices()` should use the new helper to ensure
international stocks get proper currency normalization.

## Testing Plan

### Unit Tests
1. Test `resolve_fmp_ticker()` with known cases:
   - `("AT", "Ashtead Technology Holdings", "GBP", None)` → `"AT.L"`
   - `("AAPL", "Apple Inc", "USD", "XNAS")` → `"AAPL"` (unchanged)
   - `("RY", "Royal Bank of Canada", "CAD", "XTSE")` → `"RY.TO"`

### Integration Tests
1. Fresh Plaid sync with AT position → verify `fmp_ticker` = "AT.L"
2. Position monitor shows correct price (4.035 GBP) and P&L
3. Risk analysis functions receive correct historical data for AT.L
4. US positions unaffected (continue to work as before)

### Regression Tests
1. All existing position monitor tests pass
2. Risk analysis calculations unchanged for US stocks
3. Factor intelligence correlations work for international stocks

## Status

### Completed
- [x] Investigate and document root cause
- [x] Add `exchange_mic` extraction to Plaid loader
- [x] Add `exchange_mic` extraction to SnapTrade loader
- [x] Verify Plaid returns correct `institution_price` (4.035 for AT)
- [x] Verify FMP has correct data for `AT.L` (403.5 GBp)
- [x] Identify FMP search endpoint as resolution mechanism

### Next Steps

#### 1. Configuration & Resolver
- [ ] Create `exchange_mappings.yaml` in root directory with:
  - `mic_to_fmp_suffix` - MIC → FMP suffix mappings
  - `us_exchange_mics` - US exchange MIC list (for shortcut logic)
  - `minor_currencies` - Minor currency detection (GBp → GBP with divisor)
  - `currency_aliases` - Currency aliases for matching (GBX → GBP)
  - `mic_to_exchange_short_name` - For search disambiguation
- [ ] Implement `resolve_fmp_ticker()` in `utils/ticker_resolver.py`
  - Only skip resolution when `exchange_mic` is US venue (not just USD currency)
  - Use scoring with normalized company name matching
  - Add exchange filtering for disambiguation
- [ ] Implement helper functions:
  - `normalize_currency()` - Currency alias lookup
  - `normalize_fmp_price()` - Minor currency conversion (GBp → GBP, divide by 100)
  - `normalize_company_name()` - Strip corporate suffixes for fuzzy matching
  - `fetch_fmp_quote_with_currency()` - Get price + currency for normalization
- [ ] Add resolution cache with TTL (7 days), negative cache (1 day), epoch timestamps

#### 2. Database Schema
- [ ] Create migration: `database/migrations/YYYYMMDD_add_fmp_ticker.sql`
- [ ] Update `database/schema.sql` with `fmp_ticker` column
- [ ] Update `inputs/database_client.py` INSERT/SELECT statements
- [ ] Migration backfills only confirmed US exchange positions (`exchange_mic` in US MIC list)
- [ ] Create `scripts/backfill_fmp_tickers.py` to resolve ALL remaining NULL positions
  - Includes non-USD positions (definitely need resolution)
  - Includes USD/no-MIC positions (may be ADRs, need resolution attempt)
- [ ] Run backfill script after migration

#### 3. Integration
- [ ] Update `plaid_loader.py` to call resolver and populate `fmp_ticker`
- [ ] Update `snaptrade_loader.py` to call resolver and populate `fmp_ticker`
- [ ] Update `services/position_service.py` `_enrich_with_prices()` to use `fmp_ticker`
- [ ] Audit and update all other FMP query points (`latest_price()`, `fetch_monthly_close()`, etc.)

#### 4. Testing
- [ ] Unit tests for `resolve_fmp_ticker()` with known cases:
  - US stock with MIC: `("AAPL", "Apple Inc", "USD", "XNAS")` → `"AAPL"`
  - UK stock without MIC: `("AT", "Ashtead Technology Holdings", "GBP", None)` → `"AT.L"`
  - Canadian stock with MIC: `("RY", "Royal Bank of Canada", "CAD", "XTSE")` → `"RY.TO"`
  - ADR edge case: `("BABA", "Alibaba", "USD", None)` → should attempt resolution
- [ ] Unit tests for `normalize_currency()`:
  - `normalize_currency("GBp")` → `"GBP"` (uppercase, no alias needed)
  - `normalize_currency("GBX")` → `"GBP"` (alias lookup)
  - `normalize_currency("ZAc")` → `"ZAR"` (uppercase + alias: ZAC → ZAR)
  - `normalize_currency("ILA")` → `"ILS"` (alias lookup)
  - `normalize_currency(None)` → `None` (allows skipping currency filter)
- [ ] Unit tests for `normalize_fmp_price()` (case-sensitive minor currency detection):
  - `normalize_fmp_price(403.5, "GBp")` → `(4.035, "GBP")` (pence → pounds)
  - `normalize_fmp_price(403.5, "GBP")` → `(403.5, "GBP")` (already pounds, no conversion)
  - `normalize_fmp_price(150.0, "USD")` → `(150.0, "USD")` (no conversion)
- [ ] Integration test: Fresh sync with AT position → verify `fmp_ticker` = "AT.L"
- [ ] Verify position monitor shows correct price and P&L
- [ ] Verify US positions unaffected (regression)
- [ ] Test cache behavior (TTL, negative cache)

---

## Alternatives Considered

### Option: Preserve Provider Prices Only (Rejected)

Just preserve Plaid's `institution_price` instead of overwriting with FMP.

**Why rejected:** This only masks the symptom in position pricing. The ticker
mismatch would still cause errors in:
- Risk analysis (beta, correlation calculations using `fetch_monthly_close`)
- Factor intelligence (returns, factor exposures)
- Historical price fetching for any analysis
- Portfolio risk scoring

The ticker translation issue propagates throughout the entire codebase wherever
`fetch_monthly_close(ticker)` or `latest_price(ticker)` is called.

### Option: Store Only Resolved Ticker (Rejected)

Replace the provider ticker with the resolved FMP ticker in the database.

**Why rejected:** Breaks sync reconciliation. The sync logic uses `(account_id, ticker, currency)`
to match incoming provider data with existing DB rows. If Plaid sends "AT" but DB has "AT.L",
they won't match → creates duplicate rows or orphans old data.

### Future Enhancement: Persist Provider Price/Value

Add columns to positions table:
- `price` (provider-supplied price at sync time)
- `value` (provider-supplied market value)
- `price_currency` (currency of the price)

This would preserve provider data and enable historical tracking. Not included in current
scope but could be added later.
