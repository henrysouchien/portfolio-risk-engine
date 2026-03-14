# IBKR Dual Entry Point Cleanup

**Date**: 2026-02-25
**Status**: Complete
**Risk**: Very Low — delete 1 dead file, update docs

## Context

The TODO flags confusion between `ibkr/client.py` (data reads) and `brokerage/ibkr/adapter.py` (trade execution). After investigation, the separation is architecturally correct and already well-documented in both files' docstrings. No account resolution duplication exists. The only real issue is a dead backward-compatibility shim at `services/ibkr_broker_adapter.py` that has zero code imports (only referenced in planning docs).

### Current Architecture (correct, keep as-is)

```
ibkr/client.py (IBKRClient)          — Read-only data: positions, market data, account metadata
  └── ibkr/account.py                — Account-level helpers
  └── ibkr/market_data.py            — Market data client
  └── ibkr/metadata.py               — Contract details, option chains
  └── ibkr/connection.py             — IBKRConnectionManager (shared)

brokerage/ibkr/adapter.py            — Trade execution: orders, previews, cancellations
  └── ibkr/connection.py             — IBKRConnectionManager (shared)
  └── ibkr/locks.py                  — ibkr_shared_lock (shared)

services/ibkr_broker_adapter.py      — DEAD shim (0 code imports) ← DELETE THIS
```

Both entry points share `IBKRConnectionManager` and `ibkr_shared_lock` but serve completely different domains (reads vs writes). The `brokerage/ibkr/adapter.py` docstring already documents the relationship.

## Changes

### 1. Add cross-reference docstring to `brokerage/ibkr/adapter.py`

The adapter's docstring documents its callers and dependencies but doesn't mention the read-only counterpart. Add a one-line cross-reference:

```python
"""IBKR broker adapter implementing ``BrokerAdapter`` via ``ib_async``.

Called by:
- ``services.trade_execution_service.TradeExecutionService`` for IBKR accounts.

Calls into:
- ``ibkr.connection.IBKRConnectionManager`` and IB Gateway order APIs.

Related:
- ``ibkr.client.IBKRClient`` — read-only data facade (positions, market data, metadata).
"""
```

### 2. Delete dead shim

**Delete** `services/ibkr_broker_adapter.py`:
```python
# Current contents (entire file):
"""Backward-compatible shim for extracted IBKR adapter."""
from brokerage.ibkr.adapter import IBKRBrokerAdapter, ibkr_to_common_status
__all__ = ["IBKRBrokerAdapter", "ibkr_to_common_status"]
```

Confirmed zero code imports — only referenced in docs/planning files.

### 3. Update TODO

Remove the "Architecture: Clarify IBKR Dual Entry Points" backlog item from `docs/planning/TODO.md` and archive to `docs/planning/completed/TODO_COMPLETED.md`.

## Verification

```bash
# Direct import still works
python -c "from brokerage.ibkr.adapter import IBKRBrokerAdapter; print('OK')"

# No code references remain
grep -r "ibkr_broker_adapter" --include="*.py" .

# IBKR tests pass
pytest tests/ -x -q --timeout=10 -k "ibkr"

# Full test suite unaffected
pytest tests/ -x -q --timeout=30
```
