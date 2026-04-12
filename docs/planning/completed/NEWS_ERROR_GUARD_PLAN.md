# NEWS_ERROR_GUARD_PLAN — Fix E5 + E6

**Bugs**: E5 (`fmp_fetch` 100% error in risk-review, empty news query) and E6 (`get_portfolio_news` 50% error rate).
**Root cause**: Same — `_load_portfolio_symbols()` returns `None` → passed through to `get_news(symbols=None)` → validation error.
**Severity**: Medium. **Scope**: Small (~25 lines of logic + tests).

---

## 1. Problem Trace

```
get_portfolio_news(mode="stock", symbols=None)
  └─ _load_portfolio_symbols() → None  (no user / no positions / load failure / no newsworthy tickers)
  └─ symbols still None
  └─ get_news(symbols=None, mode="stock")
       └─ fmp/tools/news_events.py:182 guard catches it → {"status": "error", "symbols is required..."}
```

The `get_news()` guard at line 182 always catches `symbols=None` for stock/press modes and returns an error containing `"symbols is required"`. The FMP registry path (`fmp.fetch("news_stock", symbols=None)` → `registry.py ValueError`) is **never reached** — the guard returns before the `FMPClient()` is even instantiated.

The fix adds a guard earlier in `get_portfolio_news()` with portfolio-context-aware messages that distinguish between "no symbols available" and "failed to load portfolio."

### Critical dependency: `build_market_events()` fallback

`build_market_events()` at line 618 checks for `"symbols is required"` in the error string to decide whether to fall back to `get_news(mode="general")`:

```python
if (
    news_result.get("status") == "error"
    and "symbols is required" in news_result.get("error", "")
):
    news_result = get_news(mode="general", ...)
```

The new guard in `get_portfolio_news()` MUST preserve this string match so the builder fallback keeps working. The approach: include the sentinel phrase `"symbols is required"` in the new error messages, making them a superset of information (portfolio-context-aware AND matchable by the builder).

## 2. Changes

### File: `mcp_tools/news_events.py`

#### 2a. `_load_portfolio_symbols()` — return distinct failure reasons

**Current**: Returns `None` for all failure cases (no user, load error, no positions, no newsworthy tickers). Callers cannot distinguish "empty portfolio" from "backend crash."

**Change**: Return a `(str | None, str | None)` tuple: `(symbols, failure_reason)`. The failure_reason is `None` on success, or one of:

| Return | `failure_reason` |
|--------|-----------------|
| Symbols found | `None` |
| No user configured | `"no_user"` |
| Named portfolio load exception | `"load_error"` |
| Position snapshot load exception (ValueError/ConnectionError/OSError) | `"load_error"` |
| No positions found | `"no_positions"` |
| No newsworthy tickers after filtering | `"no_positions"` |

Concretely, change the 5 `return None` sites:

```python
# Line 211 (no user)
return None, "no_user"

# Line 223 (named portfolio exception)
return None, "load_error"

# Line 236 (position snapshot exception)
return None, "load_error"

# Line 249 (no positions)
return None, "no_positions"

# Line 270 (no newsworthy tickers)
return None, "no_positions"
```

And the success return at line 278:
```python
return ",".join(sorted(top_tickers)), None
```

#### 2b. `get_portfolio_news()` — guard with context-aware message preserving builder match

**Location**: `get_portfolio_news()`, lines 295–320

**Current code** (lines 295–306):
```python
    auto_filled = False
    if mode in ("stock", "press") and not symbols:
        symbols = _load_portfolio_symbols(
            user_email=user_email,
            user_id=user_id,
            portfolio_name=portfolio_name,
            use_cache=use_cache,
            account=account,
        )
        if symbols:
            auto_filled = True
```

Then line 307 calls `get_news(symbols=symbols, ...)` with `symbols` still `None`.

**Fix**: Unpack the tuple return and add a guard with failure-reason-aware messages. Also strip whitespace from explicit `symbols` to catch whitespace-only input.

```python
    auto_filled = False

    # Normalize whitespace-only symbols to None
    if symbols and not symbols.strip():
        symbols = None

    if mode in ("stock", "press") and not symbols:
        loaded, failure_reason = _load_portfolio_symbols(
            user_email=user_email,
            user_id=user_id,
            portfolio_name=portfolio_name,
            use_cache=use_cache,
            account=account,
        )
        if loaded:
            symbols = loaded
            auto_filled = True

    # Guard: mode requires symbols but auto-fill failed and none provided
    if mode in ("stock", "press") and not symbols:
        if failure_reason == "load_error":
            msg = (
                "symbols is required: failed to load portfolio positions. "
                "Try again or specify symbols explicitly (e.g., symbols='AAPL,MSFT')."
            )
        else:
            msg = (
                "symbols is required: no portfolio symbols available for news lookup. "
                "Either specify symbols explicitly (e.g., symbols='AAPL,MSFT') "
                "or ensure the portfolio has loaded positions."
            )
        return {
            "status": "error",
            "error": msg,
        }

    result = get_news(...)
```

Key design decisions:
- Both messages contain `"symbols is required"` so `build_market_events()` fallback string match works unchanged.
- Load failures get a distinct message so an agent/user can tell "backend broke" from "empty portfolio."
- `failure_reason` variable is scoped: initialized as `None` before the `if` block so it's available in the guard even when the `if` block doesn't execute (explicit symbols provided → guard won't fire anyway).

#### 2c. `get_portfolio_events_calendar()` — same tuple unpack

Update the `_load_portfolio_symbols()` call site at line 339 to unpack the tuple:

```python
    if not symbols and event_type in _PORTFOLIO_CALENDAR_TYPES:
        loaded, _ = _load_portfolio_symbols(...)
        if loaded:
            symbols = loaded
            auto_filled = True
```

(Calendar doesn't need the error guard — it handles missing symbols gracefully via unfiltered results.)

#### 2d. Any other call sites

Search for all `_load_portfolio_symbols(` calls and update to unpack the tuple. Expected: `get_portfolio_news`, `get_portfolio_events_calendar`, and `_load_portfolio_weights` (which calls the same snapshot loader separately, not `_load_portfolio_symbols`). No other call sites expected.

### No changes to `build_market_events()`

The builder's `"symbols is required"` check at line 618 continues to work because the new error messages contain that exact substring. No changes needed.

### No changes to `fmp/tools/news_events.py`

The existing guard at line 182 in `get_news()` is correct as a defense-in-depth layer. It remains unchanged. With the new guard in `get_portfolio_news()`, the `get_news()` guard will only fire for direct callers who pass `symbols=None`.

## 2e. Existing test updates for `_load_portfolio_symbols()` return type change

The return type change from `str | None` to `(str | None, str | None)` breaks **27 existing test callsites** in `tests/mcp_tools/test_news_events_portfolio.py`. These split into two categories:

### Category A: Direct calls (13 tests) — unpack return tuple + update assertions

These tests call `_load_portfolio_symbols()` directly and assert on the return value. Each must change from `result = _load_portfolio_symbols(...)` to `result, reason = _load_portfolio_symbols(...)`, and assertions must target the unpacked values.

| Line | Test | Current assertion | New assertion |
|------|------|------------------|---------------|
| 79 | `test_load_portfolio_symbols_success` | `assert result is not None`; `result.split(",")` | `assert result is not None`; `result.split(",")` (unchanged); add `assert reason is None` |
| 103 | `test_load_portfolio_symbols_no_user` | `assert result is None` | `assert result is None`; add `assert reason == "no_user"` |
| 114 | `test_load_portfolio_symbols_connection_error` | `assert result is None` | `assert result is None`; add `assert reason == "load_error"` |
| 125 | `test_load_portfolio_symbols_value_error` | `assert result is None` | `assert result is None`; add `assert reason == "load_error"` |
| 136 | `test_load_portfolio_symbols_unexpected_error_propagates` | `pytest.raises(TypeError)` | No change needed (exception propagates before return) |
| 146 | `test_load_portfolio_symbols_uses_ticker_alias` | `assert result == "SHEL.L"` | `assert result == "SHEL.L"`; add `assert reason is None` |
| 158 | `test_load_portfolio_symbols_falls_back_when_ticker_alias_is_nan` | `assert result == "AAPL"` | `assert result == "AAPL"`; add `assert reason is None` |
| 197 | `test_load_portfolio_symbols_caps_at_25` | `result.split(",") if result else []` | Same pattern on `result` (unchanged); add `assert reason is None` |
| 214 | `test_load_portfolio_symbols_account_filter` | `assert result == "AAPL,MSFT"` | `assert result == "AAPL,MSFT"`; add `assert reason is None` |
| 235 | `test_load_portfolio_symbols_account_filter_no_match` | `assert result is None` | `assert result is None`; add `assert reason == "no_positions"` |
| 247 | `test_load_portfolio_symbols_account_filter_case_insensitive` | `assert result == "AAPL"` | `assert result == "AAPL"`; add `assert reason is None` |
| 261 | `test_load_portfolio_symbols_account_filter_whitespace_only` | `assert result == "AAPL,SCHD"` | `assert result == "AAPL,SCHD"`; add `assert reason is None` |
| 299 | `test_load_portfolio_symbols_uses_selected_portfolio_snapshot` | `assert result == "AAPL,MSFT"` | `assert result == "AAPL,MSFT"`; add `assert reason is None` |

### Category B: Monkeypatch mocks (14 tests) — change `return_value` to tuple

These tests mock `_load_portfolio_symbols` via `monkeypatch.setattr(news_events, "_load_portfolio_symbols", MagicMock(return_value=...))`. The mock return values must change from `str | None` to `(str | None, str | None)` tuples.

| Line | Test | Current `return_value` | New `return_value` |
|------|------|----------------------|-------------------|
| 311 | `test_portfolio_news_auto_fill` | `"AAPL,MSFT"` | `("AAPL,MSFT", None)` |
| 343 | `test_portfolio_news_explicit_symbols_override` | `"AAPL"` | `("AAPL", None)` |
| 364 | `test_portfolio_news_account_filter_ignored_with_explicit_symbols` | `"AAPL"` | `("AAPL", None)` |
| 386 | `test_portfolio_news_general_mode_skips_autofill` | `"AAPL"` | `("AAPL", None)` |
| 408 | `test_portfolio_news_general_mode_with_account_skips_autofill` | `"AAPL"` | `("AAPL", None)` |
| 429 | `test_portfolio_news_account_filter_metadata_only_on_autofill_success` | `"AAPL"` | `("AAPL", None)` |
| 441 | `test_portfolio_news_account_filter_metadata_not_set_when_autofill_fails` | `None` | `(None, "no_positions")` |
| 453 | `test_portfolio_events_calendar_auto_fill_earnings` | `"AAPL,MSFT"` | `("AAPL,MSFT", None)` |
| 484 | `test_portfolio_events_calendar_auto_fill_dividends` | `"AAPL"` | `("AAPL", None)` |
| 505 | `test_portfolio_events_calendar_ipos_no_autofill` | `"AAPL"` | `("AAPL", None)` |
| 526 | `test_portfolio_events_calendar_all_no_autofill` | `"AAPL"` | `("AAPL", None)` |
| 548 | `test_portfolio_events_calendar_market_wide_types_with_account_skip_autofill` | `"AAPL"` | `("AAPL", None)` |
| 570 | `test_portfolio_events_calendar_account_filter_metadata_only_on_autofill_success` | `"AAPL"` | `("AAPL", None)` |
| 585 | `test_portfolio_events_calendar_empty_portfolio_fallback` | `None` | `(None, "no_positions")` |

**Note on line 441**: This test (`test_portfolio_news_account_filter_metadata_not_set_when_autofill_fails`) currently mocks `return_value=None` and then asserts the `get_news()` call returns `{"status": "error", "error": "symbols is required"}`. With the new guard in `get_portfolio_news()`, this test's behavior changes: the guard will fire *before* calling `get_news()`, so `news_mock` should NOT be called. The test must be updated to assert the new guard error message and verify `news_mock.assert_not_called()`.

**Note on line 585**: Similarly, `test_portfolio_events_calendar_empty_portfolio_fallback` mocks `return_value=None`. The calendar path doesn't add a guard (per section 2c), so it just needs the tuple unpack — `(None, "no_positions")`. No behavioral change.

## 3. Test Cases

### File: `tests/mcp_tools/test_news_events_portfolio.py`

Add tests:

| # | Test | What it verifies |
|---|------|-----------------|
| 1 | `test_get_portfolio_news_returns_error_when_autofill_yields_no_positions` | `mode="stock"`, `_load_portfolio_symbols` returns `(None, "no_positions")` → `{"status": "error", "error": "...symbols is required: no portfolio symbols..."}` |
| 2 | `test_get_portfolio_news_returns_error_when_autofill_load_failure` | `mode="stock"`, `_load_portfolio_symbols` returns `(None, "load_error")` → `{"status": "error", "error": "...symbols is required: failed to load..."}` |
| 3 | `test_get_portfolio_news_press_mode_returns_error_when_autofill_yields_none` | Same for `mode="press"` with `"no_positions"` reason |
| 4 | `test_get_portfolio_news_general_mode_skips_guard` | `mode="general"` with `symbols=None` → calls `get_news` normally (no guard hit) |
| 5 | `test_get_portfolio_news_explicit_symbols_bypass_guard` | `symbols="AAPL"` provided → guard not hit, `get_news` called with symbols |
| 6 | `test_get_portfolio_news_whitespace_only_symbols_treated_as_none` | `symbols="   "` → normalized to None, guard fires, returns error |

All tests mock `_load_portfolio_symbols` → appropriate `(None, reason)` tuple and `get_news` to verify the guard fires before the downstream call.

### File: `tests/mcp_tools/test_news_events_builder.py`

Add test:

| # | Test | What it verifies |
|---|------|-----------------|
| 7 | `test_build_news_events_falls_back_to_general_on_symbol_error` | Mock `get_portfolio_news` to return `{"status": "error", "error": "symbols is required: no portfolio symbols..."}` → verify `get_news(mode="general")` is called as fallback |
| 8 | `test_build_news_events_falls_back_on_load_error_message` | Mock `get_portfolio_news` to return `{"status": "error", "error": "symbols is required: failed to load..."}` → verify `get_news(mode="general")` fallback also triggers |

These tests validate that the `"symbols is required"` substring match in `build_market_events()._build_news_events()` works with both new error message variants.

## 4. Acceptance Criteria

- `get_portfolio_news(mode="stock")` with no portfolio context returns `{"status": "error"}` with portfolio-specific message containing `"symbols is required"`
- `get_portfolio_news(mode="stock")` with backend load failure returns a distinct error message mentioning "failed to load" while still containing `"symbols is required"`
- `get_portfolio_news(mode="press")` same behavior for both cases
- `get_portfolio_news(mode="general")` unaffected (general mode doesn't need symbols)
- `get_portfolio_news(mode="stock", symbols="AAPL")` unaffected (explicit symbols bypass auto-fill)
- `get_portfolio_news(mode="stock", symbols="   ")` treated as no symbols (whitespace normalized)
- `build_market_events()._build_news_events()` fallback to `get_news(mode="general")` works with both new error messages (string match on `"symbols is required"` succeeds)
- `get_news()` defense-in-depth guard at `fmp/tools/news_events.py:182` remains intact
- `_load_portfolio_symbols()` returns `(symbols, failure_reason)` tuple — all 5 `return None` sites updated
- No changes to `fmp/` layer
- No changes to `build_market_events()` fallback logic
