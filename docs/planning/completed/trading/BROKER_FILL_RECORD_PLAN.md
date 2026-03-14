# Plan: BrokerFillRecord Dataclass

## Context

`_fetch_broker_execution_data()` in `mcp_tools/audit.py` does ad-hoc field mapping from `trade_orders` rows to `execution_result` dicts — renaming `average_fill_price` → `fill_price`, coercing Decimal → float, stringifying `brokerage_order_id`. This inline normalization has no typed contract and will need to be replicated or maintained when Schwab trades start flowing through the same path. Formalizing it into a dataclass gives us a single place to update and type-checks the contract.

## Approach

Add a `BrokerFillRecord` dataclass to `brokerage/trade_objects.py` (where `TradeExecutionResult`, `OrderResult`, etc. already live). Replace the inline dict construction in `_fetch_broker_execution_data()` with `BrokerFillRecord.from_trade_order_row()`. The dataclass owns all type coercion and field renaming.

## Changes

### 1. Add `BrokerFillRecord` to `brokerage/trade_objects.py`

```python
def _safe_float(value: Any) -> float | None:
    """Coerce a value (e.g. Decimal from DB) to float, or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class BrokerFillRecord:
    """Normalized fill record for workflow action execution_result."""

    ticker: Optional[str] = None
    side: Optional[str] = None
    fill_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    commission: Optional[float] = None
    total_cost: Optional[float] = None
    order_status: Optional[str] = None
    brokerage_order_id: Optional[str] = None
    account_id: Optional[str] = None
    broker_provider: Optional[str] = None
    filled_at: Optional[str] = None  # ISO timestamp string

    @classmethod
    def from_trade_order_row(cls, row: dict) -> "BrokerFillRecord":
        """Build from a trade_orders DB row. Handles Decimal coercion and field renaming."""
        filled_at_raw = row.get("filled_at")
        filled_at_str = None
        if filled_at_raw is not None:
            filled_at_str = filled_at_raw.isoformat() if hasattr(filled_at_raw, "isoformat") else str(filled_at_raw)

        return cls(
            ticker=row.get("ticker"),
            side=row.get("side"),
            fill_price=_safe_float(row.get("average_fill_price")),
            filled_quantity=_safe_float(row.get("filled_quantity")),
            commission=_safe_float(row.get("commission")),
            total_cost=_safe_float(row.get("total_cost")),
            order_status=row.get("order_status"),
            brokerage_order_id=str(row["brokerage_order_id"]) if row.get("brokerage_order_id") is not None else None,
            account_id=row.get("account_id"),
            broker_provider=row.get("broker_provider"),
            filled_at=filled_at_str,
        )

    def has_fill_evidence(self) -> bool:
        return (
            self.filled_quantity is not None
            and self.filled_quantity > 0
            and self.fill_price is not None
            and self.fill_price != 0
        )

    def to_dict(self) -> dict:
        """Convert to dict. Includes all fields (even None) to preserve key presence."""
        return {k: v for k, v in self.__dict__.items()}
```

**Export updates:**

- Add `BrokerFillRecord` and `_safe_float` to `__all__` in `brokerage/trade_objects.py` (line 473)
- Add `BrokerFillRecord` to explicit imports and `__all__` in `brokerage/__init__.py` (line 4, line 20)
- `core/trade_objects.py` re-exports via `from brokerage.trade_objects import *` so it picks up automatically via `__all__`

**Design notes:**

- `_safe_float()` is a module-level helper (same logic currently inline in audit.py).
- `to_dict()` preserves all keys including None values. Existing tests assert `trades[0]["fill_price"] is None` — omitting None would break them. This also matches `OrderResult.to_dict()` / `OrderStatus.to_dict()` which include all keys.
- `from_trade_order_row()` is new to this file, but it's the right pattern here — trade_objects.py dataclasses are constructed by broker adapters, while BrokerFillRecord constructs from raw DB rows with coercion. A classmethod makes the coercion self-documenting rather than scattered in callers.
- `account_id`, `broker_provider`, `filled_at` are available in the `trade_orders` schema (`SELECT *`) and belong in the fill record — they identify *which* broker and account produced the fill, and *when* execution happened.

### 2. Unify broker-owned-keys constant

The broker-owned-keys contract is currently duplicated:
- `BROKER_OWNED_KEYS` in `mcp_tools/audit.py` (line 34)
- `_WORKFLOW_ACTION_BROKER_OWNED_KEYS` in `inputs/database_client.py` (line 76)

These must always be identical. To prevent future drift, **move the canonical set to `BrokerFillRecord`** as a class-level constant, and have both consumers import it:

```python
@dataclass
class BrokerFillRecord:
    """Normalized fill record for workflow action execution_result."""

    OWNED_KEYS: ClassVar[frozenset[str]] = frozenset({
        "ticker", "side", "fill_price", "filled_quantity",
        "commission", "total_cost", "order_status", "brokerage_order_id",
        "account_id", "broker_provider", "filled_at",
    })
    # ... fields ...
```

Then:
- `mcp_tools/audit.py`: `from brokerage.trade_objects import BrokerFillRecord` and replace `BROKER_OWNED_KEYS` with `BrokerFillRecord.OWNED_KEYS`
- `inputs/database_client.py`: `from brokerage.trade_objects import BrokerFillRecord` and replace `_WORKFLOW_ACTION_BROKER_OWNED_KEYS` with `BrokerFillRecord.OWNED_KEYS`

This eliminates the duplication entirely — one constant, one import, no drift.

### 3. Update `mcp_tools/audit.py`

- Import `BrokerFillRecord` from `brokerage.trade_objects`
- Replace `BROKER_OWNED_KEYS` with `BrokerFillRecord.OWNED_KEYS`
- Replace inline dict construction loop in `_fetch_broker_execution_data()`:
  ```python
  # Before: 8-line dict literal with _safe_float() calls
  # After:
  record = BrokerFillRecord.from_trade_order_row(order)
  trades.append(record.to_dict())
  ```
- In `_fetch_broker_execution_data()`, replace `_has_fill_evidence(trade)` with `record.has_fill_evidence()` (called on the BrokerFillRecord instance *before* `to_dict()`)
- Remove `_safe_float()` from audit.py (moved to trade_objects.py)
- **Keep `_has_fill_evidence()` as a standalone function in audit.py** — `_build_incomplete_broker_warning()` at line 363 calls `_has_fill_evidence(trade)` on trade *dicts* from `broker_data["trades"]`. These dicts come out of `to_dict()` and are plain dicts, not BrokerFillRecord instances. Removing the standalone would break that call site. The dataclass method is used during construction in `_fetch_broker_execution_data()`; the standalone is used post-construction on dicts.
- `_merge_execution_result_with_broker_data()` unchanged (operates on dicts, which `to_dict()` produces)

### 4. Update `inputs/database_client.py`

- Import `BrokerFillRecord` from `brokerage.trade_objects`
- Delete `_WORKFLOW_ACTION_BROKER_OWNED_KEYS` constant (line 76-85)
- Replace all references to `_WORKFLOW_ACTION_BROKER_OWNED_KEYS` with `BrokerFillRecord.OWNED_KEYS`:
  - `_workflow_agent_only_payload()` (line 115)
  - `_apply_workflow_broker_merge()` (lines 140, 143, 145)

### 5. Tests

- Add `tests/brokerage/test_broker_fill_record.py`:
  - `from_trade_order_row()` with Decimal values → float
  - `from_trade_order_row()` with None values → None (keys still present)
  - `average_fill_price` renamed to `fill_price`
  - `brokerage_order_id` coerced to str
  - `account_id`, `broker_provider`, `filled_at` populated
  - `filled_at` datetime → ISO string conversion
  - `has_fill_evidence()` true/false cases
  - `to_dict()` includes None-valued keys (does NOT omit them)
- Existing `tests/mcp_tools/test_audit.py` tests should pass unchanged (the dict shape is identical — `to_dict()` includes all keys, so `trades[0]["fill_price"] is None` still works)
- **Add regression tests** to `tests/mcp_tools/test_audit.py` for the 3 new broker-owned fields:
  - Same-status merge strips `account_id`, `broker_provider`, `filled_at` from agent-authored top level (multi-order path)
  - Single verified order populates `account_id`, `broker_provider`, `filled_at` on flat merge
  - Same-status re-enrichment with `broker_verified=True` and unchanged trade set: assert `_workflow_agent_only_payload()` (database_client.py line 110) strips `account_id`, `broker_provider`, `filled_at` from incoming payload — preserving existing broker-owned values (exercises `_merge_same_status_execution_result()` at line 157)
  - The `_broker_order_row()` test helper must include `account_id`, `broker_provider`, `filled_at` fields
- **Add invariant test**: Assert `BrokerFillRecord.OWNED_KEYS == {f.name for f in dataclasses.fields(BrokerFillRecord)}` — exact equality catches both missing keys and stale leftover keys after renames/removals

## Key Files

| File | Change |
|------|--------|
| `brokerage/trade_objects.py` | Add `BrokerFillRecord` dataclass + `_safe_float()` + update `__all__` |
| `brokerage/__init__.py` | Add `BrokerFillRecord` to explicit imports and `__all__` |
| `mcp_tools/audit.py` | Import `BrokerFillRecord`, replace `BROKER_OWNED_KEYS` → `BrokerFillRecord.OWNED_KEYS`, replace inline dict + `_safe_float()`. Keep standalone `_has_fill_evidence()` for dict-based callers |
| `inputs/database_client.py` | Import `BrokerFillRecord`, delete `_WORKFLOW_ACTION_BROKER_OWNED_KEYS`, replace with `BrokerFillRecord.OWNED_KEYS` |
| `tests/brokerage/test_broker_fill_record.py` | New — unit tests for the dataclass |
| `tests/mcp_tools/test_audit.py` | Add regression tests for `account_id`, `broker_provider`, `filled_at` in merge paths |

## Verification

1. `pytest tests/brokerage/test_broker_fill_record.py` — dataclass unit tests
2. `pytest tests/mcp_tools/test_audit.py` — existing 34 tests pass unchanged (dict shape identical)
3. Live test: record action → accept → execute with `linked_trade_ids` → verify broker data still populates correctly
