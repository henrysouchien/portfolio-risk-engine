# Plan: Agent-Optimized Positions Output

_Created: 2026-02-24_
_Status: **COMPLETE**_
_Reference: `RISK_ANALYSIS_AGENT_FORMAT_PLAN.md` (completed — same pattern)_

## Context

`get_positions` is the most-called tool in the portfolio-mcp server — it's the first thing an agent calls to understand what the user owns. The current `format="summary"` returns 6 fields (count, total value, by_type, by_source). The agent can't answer "what's my biggest position?" or flag concentration risk from this output.

Meanwhile `format="full"` returns every field on every position (~5-15KB for 20+ positions), most of which the agent doesn't need for reasoning.

Goal: Apply the same `format="agent"` + `output="file"` pattern proven in `get_risk_analysis`.

## Current State

### Output formats

| Format | Size | What agent gets |
|--------|------|-----------------|
| `summary` | ~500B | Count, total value, by_type, by_source. Can't answer "what's my biggest position?" |
| `list` | ~2-4KB | Ticker/value/weight/provider per position. Data but no interpretation. |
| `full` | ~5-15KB | Every field on every position. Too much for context, no interpretation. |
| `by_account` | ~5-15KB | Same as full but grouped by account. Niche use case. |
| `monitor` | ~5-20KB | P&L, exposure, entry prices. Rich but large and uninterpreted. |

### What the agent actually needs

1. **Snapshot** — How big is the portfolio? How many positions? Levered?
2. **Top holdings** — The 5-10 biggest names (always the first question)
3. **Flags** — Concentration, leverage, stale data, provider errors
4. **Exposure breakdown** — By type, by currency (compact)

### What the agent does NOT need in-context

- Per-position cost basis, entry prices, P&L
- Account-level metadata (brokerage_name, account_name, account_id)
- Provider-specific fields (position_source per position)
- Cache metadata per provider

These belong in the file output for on-demand deep dives.

## Proposed Design

### Layer 1: Data accessors (on `PositionResult` in `core/result_objects.py`)

Add reusable getter methods to `PositionResult` so any consumer (MCP tools, API endpoints, tests) can extract structured views without reimplementing extraction logic.

```python
# In core/result_objects.py — PositionResult class

def get_top_holdings(self, n: int = 10) -> list[dict]:
    """Return top N non-cash positions sorted by absolute value.

    Computes weight_pct internally from position value / total_value,
    so callers don't need to pre-inject weights.
    """
    non_cash = [
        p for p in self.data.positions
        if p.get("type") != "cash" and not p["ticker"].startswith("CUR:")
    ]
    sorted_positions = sorted(non_cash, key=lambda p: abs(p.get("value", 0)), reverse=True)
    total = abs(self.total_value) if self.total_value else 0
    return [
        {
            "ticker": p["ticker"],
            "weight_pct": round(abs(p.get("value", 0)) / total * 100, 1) if total else 0,
            "value": round(p.get("value", 0), 2),
            "type": p.get("type"),
        }
        for p in sorted_positions[:n]
    ]

def get_exposure_snapshot(self) -> dict:
    """Return compact exposure breakdown: long/short/gross/net/leverage/cash/currency.

    Leverage denominator excludes positive cash (matching _calculate_live_leverage
    in mcp_tools/risk.py). Negative cash (margin debt) stays in both numerator
    and denominator.
    """
    positions = self.data.positions

    # Partition: positive cash excluded from exposure, negative cash (margin) included
    net_exposure = 0.0
    gross_exposure = 0.0
    long_value = 0.0
    short_value = 0.0
    cash_value = 0.0
    currency_totals: dict[str, float] = {}

    for p in positions:
        ticker = str(p.get("ticker", ""))
        ptype = str(p.get("type", ""))
        value = p.get("value", 0) or 0
        is_cash = ptype == "cash" or ticker.startswith("CUR:")

        if is_cash:
            cash_value += value
            if value > 0:
                continue  # positive cash excluded from exposure (same as risk.py)

        # Negative cash (margin debt) falls through here
        net_exposure += value
        gross_exposure += abs(value)
        if value > 0:
            long_value += value
        elif value < 0:
            short_value += value

        if not is_cash:
            cur = p.get("currency", "USD")
            currency_totals[cur] = currency_totals.get(cur, 0) + abs(value)

    leverage = gross_exposure / abs(net_exposure) if abs(net_exposure) > 1e-12 else 1.0

    return {
        "total_value": round(self.total_value, 2),
        "position_count": self.position_count,
        "equity_count": self.by_type.get("equity", 0),
        "etf_count": self.by_type.get("etf", 0),
        "cash_value": round(cash_value, 2),
        "cash_pct": round(cash_value / self.total_value * 100, 1) if self.total_value else 0,
        "long_exposure": round(long_value, 2),
        "short_exposure": round(short_value, 2),
        "net_exposure": round(net_exposure, 2),
        "gross_exposure": round(gross_exposure, 2),
        "leverage": round(leverage, 2),
        "sources": list(self.by_source.keys()),
        "by_type": self.by_type,
        "by_currency": {k: round(v, 2) for k, v in sorted(currency_totals.items(), key=lambda x: -x[1])},
    }
```

These getters are pure data accessors — no flags, no interpretation, just structured views of position data. Any consumer can call `result.get_top_holdings(5)` or `result.get_exposure_snapshot()`.

**Key design notes:**
- `get_top_holdings()` computes `weight_pct` internally from `abs(value) / abs(total_value)` — it does NOT depend on the `weight` field that `mcp_tools/positions.py` injects. This makes it fully self-contained and safe to call from any consumer.
- `get_exposure_snapshot()` leverage denominator excludes positive cash but includes negative cash (margin debt), exactly matching `_calculate_live_leverage()` in `mcp_tools/risk.py`.
- **Two different weight denominators by design:** `top_holdings.weight_pct` uses `total_value` (answers "what % of my portfolio is this?"), while concentration flags use `gross_non_cash` exposure (answers "what % of my risk exposure is this?"). A $46k position in a $125k portfolio is 36.9% of portfolio but 25.1% of gross exposure when there are $184k in gross non-cash positions. The agent sees both: portfolio weight in `top_holdings`, exposure weight in `flags`.

### Layer 2: Flag rules (new — `core/position_flags.py`)

Domain-level interpretive logic, following the `core/risk_flags.py` pattern. Lives in `core/` so any consumer can generate flags — not just the MCP tool.

```python
def generate_position_flags(
    positions: list[dict],
    total_value: float,
    cache_info: dict,
) -> list[dict]:
    """
    Generate actionable flags from position data.

    Each flag: {type, severity, message, ...contextual_data}
    Severity: "error" > "warning" > "info"
    """
    flags = []

    # --- Partition positions ---
    non_cash = [
        p for p in positions
        if p.get("type") != "cash" and not str(p.get("ticker", "")).startswith("CUR:")
    ]

    # --- Provider errors (severity: error) ---
    # Future: requires upstream changes to PositionService.get_all_positions()
    # to catch per-provider errors and surface them in _cache_metadata.
    # Currently, a single provider failure crashes the entire positions fetch.
    # When that's fixed, uncomment:
    #
    # for provider, info in (cache_info or {}).items():
    #     if info.get("error"):
    #         flags.append({
    #             "type": "provider_error",
    #             "severity": "error",
    #             "message": f"{provider}: {info['error']}",
    #             "provider": provider,
    #         })

    # --- Concentration flags (absolute exposure weights, non-cash only) ---
    # Use absolute value so shorts count toward concentration risk too.
    # Denominator is gross non-cash exposure (not NAV) for concentration math.
    gross_non_cash = sum(abs(p.get("value", 0)) for p in non_cash)

    if gross_non_cash > 0:
        # Single-position concentration: any position > 15% of gross exposure
        for p in non_cash:
            abs_weight = abs(p.get("value", 0)) / gross_non_cash * 100
            if abs_weight > 15:
                flags.append({
                    "type": "single_position_concentration",
                    "severity": "warning",
                    "message": f"{p['ticker']} is {abs_weight:.1f}% of exposure",
                    "ticker": p["ticker"],
                    "weight_pct": round(abs_weight, 1),
                })

        # Top-5 concentration: top 5 by absolute exposure > 60%
        sorted_by_abs = sorted(non_cash, key=lambda p: abs(p.get("value", 0)), reverse=True)
        top5_value = sum(abs(p.get("value", 0)) for p in sorted_by_abs[:5])
        top5_weight = top5_value / gross_non_cash * 100
        if top5_weight > 60:
            flags.append({
                "type": "top5_concentration",
                "severity": "info",
                "message": f"Top 5 holdings are {top5_weight:.0f}% of exposure",
                "top5_weight_pct": round(top5_weight, 1),
            })

    # --- Leverage flags ---
    # Match _calculate_live_leverage(): exclude positive cash from both sides,
    # include negative cash (margin debt).
    net_exposure = 0.0
    gross_exposure = 0.0
    for p in positions:
        ticker = str(p.get("ticker", ""))
        ptype = str(p.get("type", ""))
        value = p.get("value", 0) or 0
        is_cash = ptype == "cash" or ticker.startswith("CUR:")
        if is_cash and value > 0:
            continue
        net_exposure += value
        gross_exposure += abs(value)

    leverage = gross_exposure / abs(net_exposure) if abs(net_exposure) > 1e-12 else 1.0

    if leverage > 2.0:
        flags.append({
            "type": "high_leverage",
            "severity": "warning",
            "message": f"Portfolio is {leverage:.1f}x levered",
            "leverage": round(leverage, 2),
        })
    elif leverage > 1.1:
        flags.append({
            "type": "leveraged",
            "severity": "info",
            "message": f"Portfolio is {leverage:.2f}x levered",
            "leverage": round(leverage, 2),
        })

    # --- Cash flags ---

    cash_positions = [p for p in positions if p.get("type") == "cash" or p["ticker"].startswith("CUR:")]
    cash_value = sum(p.get("value", 0) for p in cash_positions)
    cash_pct = (cash_value / total_value * 100) if total_value else 0
    if cash_pct > 15:
        flags.append({
            "type": "cash_drag",
            "severity": "info",
            "message": f"Cash is {cash_pct:.0f}% of portfolio (${cash_value:,.0f})",
            "cash_pct": round(cash_pct, 1),
            "cash_value": round(cash_value, 2),
        })

    # --- Data quality flags ---

    # Stale cache: age > 2x provider TTL (adapts to each provider's refresh cycle)
    for provider, info in (cache_info or {}).items():
        age = info.get("age_hours")
        ttl = info.get("ttl_hours", 24)
        if age is not None and ttl and age > ttl * 2:
            flags.append({
                "type": "stale_data",
                "severity": "warning",
                "message": f"{provider} data is {age:.0f}h old (TTL {ttl}h)",
                "provider": provider,
                "age_hours": round(age, 1),
                "ttl_hours": ttl,
            })

    # Low diversification
    non_cash_count = len(non_cash)
    if non_cash_count < 5:
        flags.append({
            "type": "low_position_count",
            "severity": "info",
            "message": f"Only {non_cash_count} non-cash positions — limited diversification",
            "position_count": non_cash_count,
        })

    # Sort: warnings first, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))

    return flags
```

### Threshold constants

Hardcoded for v1, extract to config if we add more rules:

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Provider error | any error in cache_info | **Future** — requires upstream PositionService changes to catch per-provider errors |
| Single position | > 15% of gross non-cash exposure | Standard diversification threshold (uses absolute weight so shorts count) |
| Top-5 concentration | > 60% of gross non-cash exposure | Above this, idiosyncratic risk dominates |
| Leveraged | > 1.1x | Anything above 1.1 is intentional leverage |
| High leverage | > 2.0x | Elevated risk, worth flagging as warning |
| Cash drag | > 15% of total value | Meaningful drag on returns |
| Stale data | age > 2x provider TTL | Adapts to each provider's refresh cycle (e.g. 24h TTL → stale at 48h) |
| Low diversification | < 5 non-cash positions | Limited risk spreading |

### Layer 3: Agent format composer (in `mcp_tools/positions.py`)

Thin composition layer — calls Layer 1 getters and Layer 2 flags, then shapes the response. No domain logic here.

```python
def _build_agent_response(
    result: PositionResult,
    cache_info: dict,
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented position summary for agent use."""
    from core.position_flags import generate_position_flags

    # Layer 1: Data accessors (on PositionResult)
    snapshot = result.get_exposure_snapshot()
    top_holdings = result.get_top_holdings(10)

    # Layer 2: Interpretive flags (domain logic in core/)
    flags = generate_position_flags(result.data.positions, result.total_value, cache_info)

    # Layer 3: Compose response (MCP-specific shaping)
    # Split snapshot into snapshot + exposure for the agent response structure
    exposure = {
        "by_type": snapshot.pop("by_type"),
        "by_currency": snapshot.pop("by_currency"),
    }

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "top_holdings": top_holdings,
        "flags": flags,
        "exposure": exposure,
        "cache_info": cache_info,
        "file_path": file_path,
    }
```

### File output

When `output="file"`:

1. Run positions fetch as normal
2. Write combined payload to `logs/positions/positions_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned (works with any format, not just agent)

File contents — both the API response and monitor view so the agent has everything on disk:

```python
def _save_full_positions(result: PositionResult, cache_info: dict) -> str:
    """Save full position data to disk and return absolute path."""
    output_dir = Path("logs/positions")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"positions_{timestamp}.json"

    payload = {
        "api_response": result.to_api_response(),
        "monitor_view": result.to_monitor_view(),
        "cache_info": cache_info,
    }

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

## Files to Modify

### 1. Modify: `core/result_objects.py` — `PositionResult` class

**Add `get_top_holdings(n)`:**
- Returns top N non-cash positions sorted by absolute value
- Each entry: `{ticker, weight_pct, value, type}`

**Add `get_exposure_snapshot()`:**
- Returns compact exposure dict: total_value, long/short/gross/net, leverage, cash, sources, by_type, by_currency

### 2. New: `core/position_flags.py`

- `generate_position_flags(positions, total_value, cache_info) -> list[dict]`
- All flag rules from the threshold table above
- Sorted by severity (warning > info)
- Each flag: `{type, severity, message, ...contextual_data}`
- Lives in `core/` alongside `risk_flags.py` — reusable by any consumer

### 3. Modify: `mcp_tools/positions.py`

**Add `_build_agent_response()`:**
- Calls `result.get_exposure_snapshot()` and `result.get_top_holdings(10)` (Layer 1)
- Calls `generate_position_flags()` from `core/position_flags.py` (Layer 2)
- Shapes into agent response structure (Layer 3)

**Add `_save_full_positions()`:**
- Writes `to_api_response()` + `to_monitor_view()` to `logs/positions/`
- Returns absolute path

**Update `get_positions()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- Wire the new format into the format dispatch

**Update format dispatch:**

File write happens **before** format dispatch (matching `get_risk_analysis` in `mcp_tools/risk.py:417`), so `output="file"` works with any format:

```python
# File write before format dispatch — works for all formats
file_path = _save_full_positions(result, cache_info) if output == "file" else None

if format == "agent":
    return _build_agent_response(result, cache_info, file_path=file_path)
elif format == "summary":
    response = { ... existing summary logic ... }
    if file_path:
        response["file_path"] = file_path
    return response
# ... other formats: attach file_path if present
```

### 4. Modify: `mcp_server.py`

- Update `get_positions()` registration to include `format="agent"` in enum
- Add `output` parameter
- Pass through to underlying function

### 5. Update: `docs/interfaces/mcp.md`

- Add `format="agent"` to positions tool documentation
- Add `output="file"` parameter documentation

## Agent format example output

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "total_value": 125702.52,
    "position_count": 24,
    "equity_count": 18,
    "etf_count": 4,
    "cash_value": 8340.00,
    "cash_pct": 6.6,
    "long_exposure": 150980.02,
    "short_exposure": -33617.50,
    "net_exposure": 117362.52,
    "gross_exposure": 184597.52,
    "leverage": 1.57,
    "sources": ["plaid", "snaptrade"]
  },

  "top_holdings": [
    {"ticker": "DSU",  "weight_pct": 36.9, "value": 46384.00, "type": "equity"},
    {"ticker": "BXMT", "weight_pct": 9.2,  "value": 11522.00, "type": "equity"},
    {"ticker": "STWD", "weight_pct": 8.1,  "value": 10181.00, "type": "equity"},
    {"ticker": "MSCI", "weight_pct": 7.5,  "value": 9428.00,  "type": "equity"},
    {"ticker": "SLV",  "weight_pct": 4.3,  "value": 5405.00,  "type": "etf"},
    {"ticker": "CBL",  "weight_pct": 4.2,  "value": 5279.00,  "type": "equity"},
    {"ticker": "NLY",  "weight_pct": 3.8,  "value": 4777.00,  "type": "equity"},
    {"ticker": "CTRE", "weight_pct": 3.5,  "value": 4400.00,  "type": "equity"},
    {"ticker": "GNL",  "weight_pct": 2.9,  "value": 3645.00,  "type": "equity"},
    {"ticker": "RITM", "weight_pct": 2.8,  "value": 3520.00,  "type": "equity"}
  ],

  "flags": [
    {
      "type": "single_position_concentration",
      "severity": "warning",
      "message": "DSU is 25.1% of exposure",
      "ticker": "DSU",
      "weight_pct": 25.1
    },
    {
      "type": "leveraged",
      "severity": "info",
      "message": "Portfolio is 1.57x levered",
      "leverage": 1.57
    }
  ],

  "exposure": {
    "by_type": {"equity": 18, "etf": 4, "cash": 2},
    "by_currency": {"USD": 184574.59, "GBP": 22.93}
  },

  "cache_info": {
    "plaid": {"age_hours": 2.3, "ttl_hours": 24, "from_cache": true},
    "snaptrade": {"age_hours": 1.1, "ttl_hours": 24, "from_cache": true},
    "schwab": {"age_hours": null, "ttl_hours": 24, "from_cache": false}
  },

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot` | "How big is this portfolio? Levered? How many positions?" |
| `top_holdings` | "What are the biggest names?" |
| `flags` | "What should I flag to the user right now?" |
| `exposure` | "How is it split across types and currencies?" |
| `cache_info` | "Is this data fresh?" |
| `file_path` | "Where can I dig into per-position detail?" |

## Compatibility

- All existing formats (`full`, `summary`, `list`, `by_account`, `monitor`) unchanged
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"full"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)

## Decisions

1. **Top holdings capped at 10.** Enough for agent context, keeps response compact. Cash/CUR positions excluded from the list.
2. **Flags are position-only.** No risk analysis flags here — those come from `get_risk_analysis(format="agent")`. Position flags cover: concentration, leverage, cash drag, data staleness, diversification.
3. **Exposure by currency uses absolute values.** Agent needs to know "how much is in GBP" not "net GBP exposure" (net is in snapshot).
4. **File contains both api_response and monitor_view.** Two complementary views — API has all raw fields, monitor has computed P&L/exposure. Agent can grep either.
5. **Three-layer separation matches `get_risk_analysis` pattern.** Data accessors (`get_top_holdings`, `get_exposure_snapshot`) live on `PositionResult` in `core/result_objects.py`. Flags (`generate_position_flags`) live in `core/position_flags.py` alongside `core/risk_flags.py`. MCP composer in `mcp_tools/positions.py` only does composition + file I/O.
6. **Leverage excludes positive cash, includes negative cash (margin debt).** Matches `_calculate_live_leverage()` in `mcp_tools/risk.py` exactly: positive cash skipped, negative cash (margin debt) contributes to both net and gross exposure.
7. **Single-position threshold at 15%.** Lower than the 20% in the audit sketch — 15% is more useful as an early warning. At 20%, you're already very concentrated.
8. **`output="file"` writes to `logs/positions/`** (gitignored directory, same pattern as `logs/risk_analysis/`).
9. **Concentration uses absolute exposure weights on non-cash only.** Denominator is gross non-cash exposure, not NAV. This means large shorts count toward concentration risk (a $50k short in a $200k portfolio is 25% concentration, not ignored). Cash is excluded from concentration math entirely.
10. **Stale data threshold is TTL-relative.** `age > 2x TTL` adapts to each provider (e.g. 24h TTL → stale at 48h, 1h TTL → stale at 2h). More robust than a hardcoded hour cutoff.
11. **Provider error flags deferred to v2.** Currently `PositionService.get_all_positions()` has no try/except around individual provider fetches — a single provider failure crashes the entire call. To support per-provider error flags, we'd need: (a) upstream change to catch per-provider errors and surface them in `_cache_metadata`, (b) `_build_cache_info()` enhancement to forward error strings. The flag consumer code is sketched in the plan (commented out) and ready to activate once the producer exists.

## Test Plan

### `core/result_objects.py` — PositionResult getter tests

- `test_get_top_holdings_default` — returns top 10 non-cash positions sorted by value
- `test_get_top_holdings_excludes_cash` — no CUR: or cash type in results
- `test_get_top_holdings_custom_n` — `get_top_holdings(3)` returns exactly 3
- `test_get_top_holdings_empty` — empty positions returns empty list
- `test_get_top_holdings_no_weight_injection` — works without pre-injected `weight` field (self-contained)
- `test_get_exposure_snapshot_fields` — all expected fields present and typed correctly
- `test_get_exposure_snapshot_leverage` — leverage calculated correctly (positive cash excluded, margin included)
- `test_get_exposure_snapshot_currency_breakdown` — correct grouping by currency

### `core/position_flags.py` tests

- `test_single_position_concentration_flag` — position > 15% of gross non-cash exposure triggers warning
- `test_single_position_below_threshold` — position at 14% of gross exposure does not trigger
- `test_concentration_uses_absolute_weights` — large short position ($50k short in $200k portfolio) triggers concentration warning
- `test_concentration_excludes_cash` — cash position does not appear in concentration flags
- `test_top5_concentration_flag` — top 5 > 60% of gross exposure triggers info
- `test_leverage_excludes_positive_cash` — positive cash excluded from leverage denominator
- `test_leverage_includes_margin_debt` — negative cash (margin debt) included in leverage calc
- `test_leverage_flag_info` — leverage 1.2 triggers info
- `test_leverage_flag_warning` — leverage 2.5 triggers warning
- `test_no_leverage_flag` — leverage 1.0 produces no flag
- `test_cash_drag_flag` — cash > 15% triggers info
- `test_stale_data_flag_ttl_relative` — provider age > 2x TTL triggers warning (e.g. 25h with 12h TTL)
- `test_stale_data_within_2x_ttl` — provider age 30h with 24h TTL does not trigger
- `test_low_position_count_flag` — < 5 non-cash positions triggers info
- `test_flags_sorted_by_severity` — errors before warnings before info
- `test_empty_positions_no_crash` — empty list produces no flags, no crash

### `mcp_tools/positions.py` agent format tests

- `test_agent_format_structure` — all top-level keys present (snapshot, top_holdings, flags, exposure, cache_info, file_path)
- `test_agent_format_calls_getters` — verify it delegates to `get_top_holdings()` and `get_exposure_snapshot()`
- `test_agent_format_snapshot_no_type_or_currency` — by_type/by_currency extracted into exposure, not in snapshot

### File output tests

- `test_file_output_creates_file` — file written to logs/positions/
- `test_file_output_contains_both_views` — api_response and monitor_view keys present
- `test_file_output_returns_file_path` — file_path in response is valid path
- `test_inline_output_no_file` — output="inline" does not create file, file_path is null

## Implementation Order

1. Add `get_top_holdings()` and `get_exposure_snapshot()` to `PositionResult` in `core/result_objects.py`
2. Create `core/position_flags.py` with `generate_position_flags()`
3. Add `_build_agent_response()` and `_save_full_positions()` to `mcp_tools/positions.py`
4. Add `format="agent"` and `output` parameter to `get_positions()` in `mcp_tools/positions.py`
5. Update `mcp_server.py` registration (add agent to format enum, add output param)
6. Write tests (getters → flags → composer)
7. Verify via MCP live call: `get_positions(format="agent")`
