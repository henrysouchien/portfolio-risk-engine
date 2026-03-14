# Position Ingestion Contract — Schema & Validation Layer

## Context

Phase A Step 2 (CSV Position Import) needs a proper foundation before building normalizers or providers. The current plan jumps straight from "parse CSV" to "save JSON" without a formal contract defining what valid position data looks like.

The system already has `PositionsData` (`portfolio_risk_engine/data_objects.py:301`) which validates positions at the analysis layer. But there's no ingestion-specific schema that:
1. Defines exactly what a normalizer must produce
2. Validates data at the boundary (before storage)
3. Gives clear error messages when data is wrong
4. Documents the contract for agent-created normalizers

This plan defines that contract as a standalone module, then updates the Phase A plan to use it.

---

## Existing Downstream Contract (PositionsData)

From `portfolio_risk_engine/data_objects.py:301-400`:

**Required per position:**
| Field | Type | Constraint |
|-------|------|------------|
| `ticker` | str | Non-empty |
| `quantity` | number | Finite (rejects NaN, inf, bool) |
| `value` | number | Finite |
| `type` | str | Non-empty. Valid: `"equity"`, `"cash"`, `"option"`, `"derivative"`, `"bond"`, `"mutual_fund"`, `"fund"` |
| `position_source` | str | Non-empty |
| `currency` | str | Non-empty. Nullable ONLY when `type == "cash"` or `ticker.startswith("CUR:")` — `None` is acceptable, empty string `""` is NOT |

**Optional per position:**
| Field | Type | Default |
|-------|------|---------|
| `name` | str | `""` |
| `price` | float | `None` (unknown — PositionsData converts NaN to None via from_dataframe) |
| `cost_basis` | float | `None` |
| `account_id` | str | `""` |
| `account_name` | str | `""` |
| `brokerage_name` | str | `""` |
| `fmp_ticker` | str | `""` |
| `cusip` | str | `""` |
| `isin` | str | `""` |
| `figi` | str | `""` |
| `exchange_mic` | str | `""` |
| `is_cash_equivalent` | bool | `False` |

---

## Ingestion Schema Design

### New file: `inputs/position_schema.py`

A formal schema that sits between normalizer output and storage. This is the "reverse API" — the contract that any data source (normalizer, manual entry, API) must satisfy to enter the system.

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PositionType(str, Enum):
    """Valid position types. Maps to downstream PositionsData.type values.

    Canonical types (from config/security_type_mappings.yaml canonical_types list):
      equity, etf, cash, mutual_fund, fund, bond, crypto, derivative, warrant, commodity

    Additional types used in the codebase but not in the YAML canonical list:
      option (used by IBKR/Schwab normalizers, derivative subtype)
      other (used by Plaid for unknown securities)

    Accepted aliases (mapped to canonical in to_dict()):
      cryptocurrency -> crypto, fixed_income -> bond, loan -> bond

    Provider type coverage (AFTER normalizer mapping, not raw codes):
    - IBKR Flex: equity, option, derivative, bond, mutual_fund, cash
    - Schwab: equity, option, mutual_fund, cash, bond
    - Plaid: equity, etf, mutual_fund, cash, bond, crypto, derivative, fund, other
      (Plaid raw types like "fixed income", "cryptocurrency", "loan" are mapped
       by the normalizer using parse_position_type() before PositionRecord creation)
    - SnapTrade: equity, etf, fund, bond, crypto, warrant, derivative, cash
      (SnapTrade raw codes like "et", "cs", "oef" are mapped by the SnapTrade
       normalizer using SNAPTRADE_TYPE_MAP before PositionRecord creation)

    NOTE: Raw provider codes (SnapTrade "et"/"oef"/"cs", Plaid "fixed income")
    are NOT handled by PositionType or parse_position_type(). Each normalizer
    is responsible for mapping provider-native codes to PositionType values
    before constructing PositionRecord. parse_position_type() only handles
    case/whitespace normalization (e.g. "Fixed Income" -> "fixed_income").
    """
    # Canonical types (from config/security_type_mappings.yaml canonical_types)
    EQUITY = "equity"
    ETF = "etf"
    CASH = "cash"
    OPTION = "option"              # Not in YAML canonical_types but used by IBKR/Schwab normalizers
    DERIVATIVE = "derivative"
    BOND = "bond"
    MUTUAL_FUND = "mutual_fund"
    FUND = "fund"
    CRYPTO = "crypto"
    WARRANT = "warrant"
    COMMODITY = "commodity"
    OTHER = "other"                # Not in YAML canonical_types but used by Plaid for unknown types

    # Aliases (accepted at ingestion, canonicalized in to_dict())
    CRYPTOCURRENCY = "cryptocurrency"  # -> crypto
    FIXED_INCOME = "fixed_income"      # -> bond
    LOAN = "loan"                      # -> bond


# Canonicalization mapping: normalize provider-native type aliases to canonical types.
# Canonical forms match config/security_type_mappings.yaml and constants.py.
# crypto is canonical (not cryptocurrency) per security_type_mappings.yaml:70
CANONICAL_TYPE: dict[PositionType, PositionType] = {
    PositionType.CRYPTOCURRENCY: PositionType.CRYPTO,
    PositionType.FIXED_INCOME: PositionType.BOND,
    PositionType.LOAN: PositionType.BOND,
}


def canonicalize_type(t: PositionType) -> PositionType:
    """Return the canonical form of a position type."""
    return CANONICAL_TYPE.get(t, t)


def parse_position_type(raw: str) -> PositionType:
    """Parse a raw type string into PositionType.

    Handles case/whitespace normalization only:
    - "Fixed Income" -> "fixed_income" -> PositionType.FIXED_INCOME
    - "mutual fund" -> "mutual_fund" -> PositionType.MUTUAL_FUND
    - "  Equity  " -> "equity" -> PositionType.EQUITY

    Does NOT handle provider-native codes (SnapTrade "et"/"oef"/"cs", etc.).
    Those must be mapped by the normalizer before calling this function.

    Raises ValueError if the normalized string is not a valid PositionType.
    """
    normalized = raw.strip().lower().replace(" ", "_")
    try:
        return PositionType(normalized)
    except ValueError:
        raise ValueError(
            f"Unknown position type: {raw!r} (normalized: {normalized!r}). "
            f"Valid types: {[t.value for t in PositionType]}"
        )


@dataclass(frozen=True)
class PositionRecord:
    """A single validated position record.

    This is the ingestion contract — any data source that produces positions
    must create PositionRecord instances. Validation happens at construction.

    Required fields must be provided. Optional fields have sensible defaults.
    Once created, the record is immutable (frozen dataclass).
    """
    # --- Required fields (no defaults) ---
    ticker: str
    quantity: float
    value: float
    type: PositionType
    currency: Optional[str]       # None for cash/CUR: positions, non-empty string otherwise

    # --- Required with default ---
    position_source: str = "csv"  # Non-empty. Default "csv". The import layer
                                  # overrides this to "csv_{source_key}" for BOTH
                                  # DB and filesystem storage (scoped replacement
                                  # per source_key). The default "csv" is only used
                                  # if no import layer sets it — in practice, all
                                  # import paths set "csv_{source_key}" explicitly.

    # --- Optional fields (with defaults) ---
    name: str = ""
    price: Optional[float] = None       # None = unknown (not 0.0, not NaN)
    cost_basis: Optional[float] = None  # None = unknown
    account_id: str = ""
    account_name: str = ""
    brokerage_name: str = ""

    # Security identifiers (optional)
    fmp_ticker: str = ""
    cusip: str = ""
    isin: str = ""
    figi: str = ""
    exchange_mic: str = ""

    # Provider-specific passthrough (optional)
    is_cash_equivalent: bool = False
    extra: dict = field(default_factory=dict)  # Flat dict of JSON primitives (no nested dicts/lists)

    # Fields that are part of the validated schema — extra keys MUST NOT collide with these.
    _RESERVED_KEYS: frozenset = field(default=frozenset({
        "ticker", "quantity", "value", "type", "currency", "position_source",
        "name", "price", "cost_basis", "account_id", "account_name",
        "brokerage_name", "fmp_ticker", "cusip", "isin", "figi",
        "exchange_mic", "is_cash_equivalent",
    }), init=False, repr=False, compare=False)

    def __post_init__(self):
        """Validate all fields at construction time."""
        errors = []

        # Required string fields: non-empty
        if not isinstance(self.ticker, str) or not self.ticker.strip():
            errors.append("ticker must be a non-empty string")

        # position_source: required non-empty (downstream PositionsData requires it)
        if not isinstance(self.position_source, str) or not self.position_source.strip():
            errors.append("position_source must be a non-empty string")

        # currency: None is OK for cash/CUR: positions, non-empty string otherwise.
        # Empty string "" is NOT valid (PositionsData rejects it at data_objects.py:371).
        is_cash_like = (
            self.type == PositionType.CASH
            or (isinstance(self.ticker, str) and self.ticker.startswith("CUR:"))
        )
        if self.currency is None:
            if not is_cash_like:
                errors.append("currency must be a non-empty string (None only allowed for cash/CUR: positions)")
        elif not isinstance(self.currency, str) or not self.currency.strip():
            errors.append("currency must be a non-empty string or None (for cash/CUR:), not empty string")

        # Required numeric fields: finite (not NaN, not inf, not bool)
        for fname in ("quantity", "value"):
            val = getattr(self, fname)
            if isinstance(val, bool):
                errors.append(f"{fname} must be a number, not bool")
            elif not isinstance(val, (int, float)):
                errors.append(f"{fname} must be a number, got {type(val).__name__}")
            elif not math.isfinite(val):
                errors.append(f"{fname} must be finite, got {val}")

        # Type enum validation
        if not isinstance(self.type, PositionType):
            errors.append(f"type must be a PositionType enum, got {type(self.type).__name__}")

        # Optional numeric fields: if provided (not None), must be finite
        for fname in ("price", "cost_basis"):
            val = getattr(self, fname)
            if val is not None:
                if isinstance(val, bool):
                    errors.append(f"{fname} must be a number or None, not bool")
                elif not isinstance(val, (int, float)):
                    errors.append(f"{fname} must be a number or None, got {type(val).__name__}")
                elif not math.isfinite(val):
                    errors.append(f"{fname} must be finite or None, got {val}")

        # Optional string fields: must be str (allows empty, but rejects non-str types)
        for fname in ("name", "account_id", "account_name", "brokerage_name",
                       "fmp_ticker", "cusip", "isin", "figi", "exchange_mic"):
            val = getattr(self, fname)
            if not isinstance(val, str):
                errors.append(f"{fname} must be a string, got {type(val).__name__}")

        # is_cash_equivalent: must be bool (not truthy int, etc.)
        if not isinstance(self.is_cash_equivalent, bool):
            errors.append(f"is_cash_equivalent must be bool, got {type(self.is_cash_equivalent).__name__}")

        # extra: flat dict of JSON primitives, no reserved key collisions.
        # Flat = no nested dicts or lists. This keeps the contract simple, JSON-safe,
        # and prevents deeply-nested non-serializable values from sneaking through.
        # Provider metadata (security_type, snaptrade_type_code, etc.) is always flat.
        if not isinstance(self.extra, dict):
            errors.append(f"extra must be a dict, got {type(self.extra).__name__}")
        else:
            # Check for reserved key collisions (extra MUST NOT overwrite validated fields)
            collisions = set(self.extra.keys()) & self._RESERVED_KEYS
            if collisions:
                errors.append(f"extra contains reserved keys that would overwrite validated fields: {sorted(collisions)}")
            # Validate: string keys, flat JSON-primitive values only
            _FLAT_TYPES = (str, int, float, bool, type(None))
            for k, v in self.extra.items():
                if not isinstance(k, str):
                    errors.append(f"extra key must be str, got {type(k).__name__}: {k!r}")
                elif not isinstance(v, _FLAT_TYPES):
                    errors.append(
                        f"extra[{k!r}] must be a flat JSON primitive "
                        f"(str/int/float/bool/None), got {type(v).__name__}"
                    )
                elif isinstance(v, float) and not math.isfinite(v):
                    errors.append(f"extra[{k!r}] must be finite, got {v}")

        if errors:
            raise ValueError(
                f"Invalid position record (ticker={self.ticker!r}): " +
                "; ".join(errors)
            )

    def to_dict(self) -> dict:
        """Convert to dict matching PositionsData per-position schema.

        - type enum -> canonical string value (aliases resolved)
        - currency None preserved (not converted to "")
        - price/cost_basis None preserved (PositionsData handles None correctly)
        - extra fields merged into top-level dict for provider passthrough
          (validated: no reserved key collisions, all values JSON-serializable)

        The output is guaranteed JSON-safe: no NaN, no inf, no non-serializable types.
        This guarantee holds because __post_init__ validates all core fields and extra.
        """
        d = {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "value": self.value,
            "type": canonicalize_type(self.type).value,  # enum -> canonical string
            "currency": self.currency,  # None preserved for cash
            "name": self.name,
            "price": self.price,        # None = unknown
            "cost_basis": self.cost_basis,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "brokerage_name": self.brokerage_name,
            "position_source": self.position_source,
            "fmp_ticker": self.fmp_ticker,
            "cusip": self.cusip,
            "isin": self.isin,
            "figi": self.figi,
            "exchange_mic": self.exchange_mic,
            "is_cash_equivalent": self.is_cash_equivalent,
        }
        # Merge extra fields (provider-specific passthrough)
        if self.extra:
            d.update(self.extra)
        return d
```

### NormalizeResult uses PositionRecord

```python
@dataclass
class NormalizeResult:
    """Output contract for all normalizers.

    Every normalizer's normalize() function MUST return this.

    Multi-account support: A single CSV file may contain positions from multiple
    accounts (e.g. Schwab "All Accounts" export, IBKR multi-account statements).
    Per-position account info is carried in PositionRecord.account_id and
    PositionRecord.account_name — NOT in a single top-level field.

    brokerage_name is the brokerage-level identifier (e.g. "Interactive Brokers",
    "Charles Schwab") — one per normalizer, not per account.

    Error semantics: `errors` collects per-row validation failures from
    try_build_position(). The import tool is all-or-nothing: if any errors
    exist, the import is rejected. dry_run=True shows all errors for review.
    """
    positions: list[PositionRecord]   # Validated position records (may span multiple accounts)
    errors: list[str]                 # Per-row validation failures (from try_build_position)
    warnings: list[str]               # Non-fatal issues (e.g. "3 positions missing cost basis")
    brokerage_name: str               # Brokerage identifier (matches codebase convention)
    skipped_rows: int = 0             # Rows that were filtered out
    base_currency: str = "USD"        # Statement base currency (from account info section)
```

### Batch construction helper

```python
def try_build_position(
    row_index: int,
    **kwargs,
) -> tuple[Optional[PositionRecord], Optional[str]]:
    """Try to construct a PositionRecord. Returns (record, None) or (None, error_message).

    Use this in normalizers to collect per-row errors without aborting the entire batch.
    """
    try:
        return PositionRecord(**kwargs), None
    except (ValueError, TypeError) as e:
        ticker = kwargs.get("ticker", "?")
        return None, f"Row {row_index} (ticker={ticker!r}): {e}"


def build_position_batch(
    rows: list[dict],
) -> tuple[list[PositionRecord], list[str]]:
    """Build PositionRecord list from dicts, collecting all errors.

    Each dict has keys matching PositionRecord fields.
    Returns (valid_records, error_messages) so the caller can decide
    whether to proceed (e.g. dry_run shows warnings) or abort.
    """
    valid = []
    errors = []
    for i, row in enumerate(rows):
        record, error = try_build_position(row_index=i, **row)
        if record is not None:
            valid.append(record)
        else:
            errors.append(error)
    return valid, errors
```

### Validation flow

```
Raw CSV lines
    |
Normalizer (detect + normalize)
    |
    |-- Per row: try_build_position() -> (PositionRecord | None, error | None)
    |-- Collect valid records + error messages
    |
NormalizeResult (validated PositionRecords + warnings)
    |
import_portfolio MCP tool
    |-- dry_run=True: show preview + any errors/warnings
    |-- dry_run=False: [record.to_dict() for record in result.positions]
    |
Save to JSON -> CSVPositionProvider -> PositionsData (second validation)
```

Two validation layers:
1. **PositionRecord construction** — at ingestion boundary (normalizer output). Per-row errors collected via `try_build_position()`.
2. **PositionsData validation** — at analysis boundary (when positions are loaded from JSON). Safety net for the analysis pipeline.

**Intentional strictness**: PositionRecord is deliberately stricter than PositionsData
for optional numeric fields (`price`, `cost_basis`). PositionsData does not validate
these at construction time — it loosely handles them during conversion. PositionRecord
rejects `inf` values early to prevent bad data from ever entering storage. This is
the "catch it at the boundary" principle — stricter ingestion, lenient analysis.

### Conversion boundary: PositionRecord -> DataFrame

`CSVPositionProvider.fetch_positions()` reads JSON, reconstructs dicts, and builds a DataFrame:

```python
# In providers/csv_positions.py
def fetch_positions(self, user_email: str, **kwargs) -> pd.DataFrame:
    """Read positions from JSON and return DataFrame for PositionService."""
    positions_file = self._resolve_path(user_email)
    with open(positions_file) as f:
        data = json.load(f)

    # Flatten all sources into one list
    # Storage schema: {"sources": {"source_key": {"positions": [...]}}}
    all_positions = []
    for source_data in data.get("sources", {}).values():
        all_positions.extend(source_data.get("positions", []))
    if not all_positions:
        return pd.DataFrame()

    # JSON round-trip: dicts already match PositionsData schema
    # (saved via PositionRecord.to_dict(), None preserved for currency/price/cost_basis)
    df = pd.DataFrame(all_positions)
    return df
```

This DataFrame then flows into `PositionsData.from_dataframe()` which handles
`None` → `NaN` conversion for numeric columns and validates the full contract.

---

## Files

| File | Purpose |
|------|---------|
| New: `inputs/position_schema.py` | `PositionType` enum, `CANONICAL_TYPE` mapping, `canonicalize_type()`, `parse_position_type()`, `PositionRecord` dataclass, `NormalizeResult` dataclass, `try_build_position()`, `build_position_batch()` |
| Modify: `inputs/normalizers/*.py` | Normalizers return `NormalizeResult` with `PositionRecord` instances via `try_build_position()` |
| Modify: `providers/csv_positions.py` (from Phase A plan) | Reads JSON dicts, builds DataFrame. JSON was validated at ingestion; `PositionsData` provides second validation as safety net. |
| Modify: `mcp_tools/import_portfolio.py` (from Phase A plan) | Uses `build_position_batch()` errors for dry_run preview warnings |

---

## Key Decisions

- **Frozen dataclass**: PositionRecord is immutable after creation. No accidental mutation between validation and storage.
- **Enum for type with canonicalization**: `PositionType` accepts all provider-native types including aliases (`cryptocurrency`, `fixed_income`, `loan`). `canonicalize_type()` maps aliases to canonical forms in `to_dict()`: `cryptocurrency` -> `crypto`, `fixed_income` -> `bond`, `loan` -> `bond`. Canonical forms match `config/security_type_mappings.yaml` and `portfolio_risk_engine/constants.py` (where `crypto` is canonical, not `cryptocurrency`).
- **None for unknown, not NaN**: `price` and `cost_basis` use `None` (not `float("nan")`) to indicate unknown. This survives JSON round-trip cleanly (`json.dumps(None)` -> `null` -> `json.loads(null)` -> `None`). NaN does not survive JSON serialization. `PositionsData.from_dataframe()` converts pandas `NaN` to `None` anyway (`data_objects.py:422`), so using `None` from the start is consistent.
- **Currency: None not ""**: Cash positions use `currency=None`, not `currency=""`. PositionsData rejects empty string but accepts None for cash/CUR: positions (`data_objects.py:371-378`).
- **position_source validated**: Required non-empty string. Default `"csv"` at the PositionRecord level. The `import_portfolio` MCP tool overrides this to `"csv_{source_key}"` (e.g. `"csv_interactive_brokers"`) for filesystem storage (Step 2) and future DB storage (Tier 3+), enabling scoped replacement per source_key. Using the same format in both paths ensures consistency if a user later adds Postgres — the DB query `LIKE 'csv_%'` will match. Brokerage identity is in `brokerage_name`.
- **extra dict for passthrough (validated, flat)**: Provider-specific fields (`security_type`, `snaptrade_type_code`, etc.) go in `extra` dict and are merged into `to_dict()` output. `__post_init__` enforces: (a) all keys are strings, (b) no key collides with reserved/validated field names, (c) all values are flat JSON primitives (str, int, float, bool, None — no nested dicts or lists), (d) no float values are NaN/inf. The flat restriction eliminates the need for recursive validation and matches the actual provider metadata shape (always key-value pairs, never nested structures).
- **is_cash_equivalent as explicit field**: Used by Plaid and referenced in `position_service.py:475,527,557,603`. Promoted to a named field rather than buried in `extra`.
- **brokerage_name not brokerage**: `NormalizeResult.brokerage_name` matches the established codebase convention used across all providers and in PositionsData dicts.
- **Multi-account via per-position fields**: Account info (`account_id`, `account_name`) lives on each `PositionRecord`, not on `NormalizeResult`. This handles multi-account CSVs (Schwab "All Accounts", IBKR multi-account) where positions from different accounts are in one file. `NormalizeResult` only carries brokerage-level info and statement base currency.
- **try_build_position for batch errors**: Since `PositionRecord.__post_init__` raises on invalid data, normalizers use `try_build_position()` to catch per-row errors and continue processing. This enables dry_run to show all issues, not just the first one.
- **No pandas dependency in schema**: `PositionRecord` is pure Python. DataFrame conversion happens at the provider boundary (`CSVPositionProvider`), keeping the schema module lightweight and importable by agent-created normalizers.
- **Value derivation is the normalizer's responsibility**: `PositionRecord` requires finite `value`. The normalizer derives it: (1) use CSV value column if present, (2) compute `quantity × price` if both available, (3) set `value = 0.0` with a warning if neither available (downstream FMP re-pricing will fill it). Currency is preserved as-is from the CSV — FX conversion happens downstream in the analysis pipeline, not at ingestion.

---

## Verification

1. Unit tests for `PositionRecord` — core validation:
   - Valid construction with all required fields
   - Rejects empty ticker, NaN quantity, inf value, bool quantity
   - Accepts None price/cost_basis (optional)
   - Rejects invalid PositionType string
   - Currency: None valid only for cash/CUR: positions; empty string always rejected
   - position_source: rejects empty string
   - Optional string fields: rejects non-str types (e.g. `name=123`, `cusip=datetime.now()`)
   - is_cash_equivalent: rejects non-bool (e.g. int 1, string "true")
   - `to_dict()` output: type canonicalized, currency None preserved, extra fields merged

2. Unit tests for `PositionRecord` — extra dict validation:
   - Valid extra: `{"security_type": "Common Stock", "snaptrade_type_code": "cs"}` accepted
   - Reserved key collision: `extra={"ticker": "override"}` raises ValueError listing colliding keys
   - Non-string key: `extra={123: "val"}` raises ValueError
   - NaN in extra: `extra={"score": float("nan")}` raises ValueError
   - Inf in extra: `extra={"score": float("inf")}` raises ValueError
   - Non-serializable value: `extra={"obj": datetime.now()}` raises ValueError
   - Nested dict rejected: `extra={"meta": {"key": "val"}}` raises ValueError (flat only)
   - Nested list rejected: `extra={"tags": ["a", "b"]}` raises ValueError (flat only)
   - Empty extra: `extra={}` accepted (default)

3. Unit tests for `try_build_position()`:
   - Valid row -> (record, None)
   - Invalid row -> (None, error_message with row index and ticker)

4. Unit tests for `build_position_batch()`:
   - Mixed valid/invalid rows -> returns both lists with correct counts
   - Empty batch -> ([], [])

5. Unit tests for `canonicalize_type()`:
   - `cryptocurrency` -> `crypto`, `fixed_income` -> `bond`, `loan` -> `bond`
   - Already-canonical types (`equity`, `etf`, `crypto`, `commodity`, `other`) pass through unchanged

6. Unit tests for `parse_position_type()`:
   - `"fixed income"` (with space) -> `PositionType.FIXED_INCOME`
   - `"mutual fund"` -> `PositionType.MUTUAL_FUND`
   - `"cryptocurrency"` -> `PositionType.CRYPTOCURRENCY`
   - `"  Equity  "` (whitespace/case) -> `PositionType.EQUITY`
   - `"commodity"` -> `PositionType.COMMODITY`
   - `"unknown_junk"` -> raises ValueError with helpful message
   - `"et"` (SnapTrade raw code) -> raises ValueError (normalizer must map before calling)

7. JSON round-trip test: `json.loads(json.dumps(record.to_dict()))` == `record.to_dict()` for:
   - Record with None price/cost_basis/currency (verifies None -> null -> None)
   - Record with extra dict containing strings, ints, floats, bools, None
   - Record with all optional fields populated
   - Verify that `extra={"nested": [float("nan")]}` and `extra={"nested": {"dt": datetime.now()}}` are rejected at construction (never reach to_dict)

8. Integration test: `PositionRecord.to_dict()` output -> `pd.DataFrame([...])` -> `PositionsData.from_dataframe()` succeeds without validation errors

9. End-to-end: `parse_position_type("fixed income")` -> `PositionType.FIXED_INCOME` -> `canonicalize_type()` -> `PositionType.BOND` -> `to_dict()["type"]` == `"bond"`

10. Provider coverage: Verify that every canonical type in `config/security_type_mappings.yaml` canonical_types list has a corresponding `PositionType` enum member
