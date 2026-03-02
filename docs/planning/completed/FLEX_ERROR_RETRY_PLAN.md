# IBKR Flex Report Error Response Detection + Retry

## Context

IBKR Flex downloads silently return empty data when the server responds with error code 1019 ("Statement generation in progress"). This is caused by an `ib_async` bug: the library's Phase 2 polling checks `root[0].tag == "code"` but IBKR returns `<Status>` as `root[0]`, so it exits the poll loop and returns error XML as a "valid" FlexReport. Our code then sees 0 trades, 0 cash, 0 futures MTM — all positions become synthetic and realized performance is meaningless.

The actual error XML returned:
```xml
<FlexStatementResponse timestamp="02 March, 2026 01:36 PM EST">
  <Status>Warn</Status>
  <ErrorCode>1019</ErrorCode>
  <ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>
</FlexStatementResponse>
```

## Files to Modify

| File | Change |
|------|--------|
| `ibkr/flex.py` | Add `import time`, error detection helper, error check in path loading, retry loop in download branch of `_load_flex_report()` |
| `tests/ibkr/test_flex.py` | 14 new tests |

No changes to callers — `fetch_ibkr_flex_payload()` already handles `(None, error_msg)`.

## Implementation

### 1. Add `import time` to imports (~line 13)

### 2. Add error detection helper + constants (before `_load_flex_report`, ~line 897)

```python
_FLEX_TRANSIENT_ERRORS = {1019}  # Statement generation in progress

def _check_flex_error_response(report: Any) -> tuple[int | None, str | None]:
    """Check if a FlexReport contains an error response instead of data.

    Returns (error_code, error_message) if error XML detected, else (None, None).

    IBKR error XML has a known structure with <ErrorCode> and <ErrorMessage>
    as direct children of the root element (e.g. <FlexStatementResponse> or
    <FlexQueryResponse>). We check direct children first, then fall back to
    a tree-wide search to handle any structural variations.
    """
    root = getattr(report, "root", None)
    if root is None:
        return None, None

    # Check direct children first (expected IBKR structure)
    error_code_el = root.find("ErrorCode")
    # Fallback: search entire tree for structural variations
    if error_code_el is None:
        error_code_el = root.find(".//ErrorCode")
    if error_code_el is None:
        return None, None

    try:
        code = int(error_code_el.text)
    except (TypeError, ValueError):
        # Malformed ErrorCode (non-integer) — treat as unrecognized error.
        # Log and return None so caller treats this as a non-error (no retry).
        trading_logger.warning(
            "IBKR Flex response contains non-integer ErrorCode: %r",
            getattr(error_code_el, "text", None),
        )
        return None, None

    message_el = root.find("ErrorMessage") or root.find(".//ErrorMessage")
    message = message_el.text if message_el is not None else f"IBKR Flex error {code}"

    return code, message
```

**Design decisions:**
- Checks direct children first (`root.find("ErrorCode")`) for the known IBKR structure, then falls back to tree-wide search (`root.find(".//ErrorCode")`) for structural variations. This avoids false positives from deeply nested elements while remaining resilient to XML layout changes.
- Malformed (non-integer) `ErrorCode` logs a warning and returns `(None, None)` — treated as no error, so the report flows through normal topic detection (which will flag missing sections as `partial_data`).

**Unknown error code policy:** Any integer `ErrorCode` not in `_FLEX_TRANSIENT_ERRORS` is treated as **permanent** — no retry, immediate failure with the code and message surfaced. This is the safe default: we only retry errors we explicitly know are transient.

### 3. Modify `_load_flex_report()` — both path and download branches

```python
def _load_flex_report(
    *,
    token: str = "",
    query_id: str = "",
    path: Optional[str] = None,
) -> tuple[Any | None, str | None]:
    # --- Path loading ---
    if path:
        if not Path(path).exists():
            return None, f"IBKR Flex XML file not found: {path}"
        try:
            report = FlexReport(path=path)
        except Exception as exc:
            return None, f"Failed to load IBKR Flex XML from {path}: {exc}"

        # A saved XML file could contain an error response
        error_code, error_msg = _check_flex_error_response(report)
        if error_code is not None:
            return None, f"IBKR Flex error {error_code} in {path}: {error_msg}"
        return report, None

    # --- Download ---
    if not token or not query_id:
        return None, "IBKR Flex credentials missing; skipping Flex download"

    # Retry schedule: 5s, 10s, 15s, 20s = 50s total wait before giving up.
    # Error 1019 typically resolves in 10-30s. Linear backoff keeps total
    # wall time under 60s while giving IBKR enough time to generate.
    retry_delays = [5, 10, 15, 20]
    max_attempts = len(retry_delays) + 1  # 5 total attempts

    for attempt in range(max_attempts):
        try:
            report = FlexReport(token=token, queryId=query_id)
        except Exception as exc:
            # Constructor exceptions (network errors, FlexError from Phase 1)
            # are not retried — ib_async already has its own internal retry
            # logic for Phase 1/Phase 2 polling. If it raises, the error is
            # not transient at our level.
            exc_msg = str(exc)
            if token and token in exc_msg:
                exc_msg = exc_msg.replace(token, "***")
            if query_id and query_id in exc_msg:
                exc_msg = exc_msg.replace(query_id, "***")
            return None, f"IBKR Flex download failed: {exc_msg}"

        # Check if the "successful" download is actually an error response
        error_code, error_msg = _check_flex_error_response(report)

        if error_code is None:
            # Genuine data — success
            if attempt > 0:
                trading_logger.info(
                    "IBKR Flex report succeeded on attempt %d/%d",
                    attempt + 1, max_attempts,
                )
            return report, None

        if error_code not in _FLEX_TRANSIENT_ERRORS:
            # Permanent or unknown error — don't retry
            trading_logger.error(
                "IBKR Flex error %d: %s", error_code, error_msg
            )
            return None, f"IBKR Flex error {error_code}: {error_msg}"

        # Transient error (1019) — retry if attempts remain
        if attempt < max_attempts - 1:
            delay = retry_delays[attempt]
            trading_logger.warning(
                "IBKR Flex transient error %d (%s); retrying in %ds "
                "(attempt %d/%d)",
                error_code, error_msg, delay, attempt + 1, max_attempts,
            )
            time.sleep(delay)
        else:
            trading_logger.error(
                "IBKR Flex transient error %d persisted after %d attempts: %s",
                error_code, max_attempts, error_msg,
            )
            return None, (
                f"IBKR Flex error {error_code} after {max_attempts} attempts: "
                f"{error_msg}"
            )

    # Defensive — should not be reached
    return None, "IBKR Flex download failed: unexpected retry loop exit"
```

**Key changes from v1:**
- **Path loading now checks for error XML** — a saved error response file is detected and returned as an error instead of silently yielding empty data.
- **Unknown error codes treated as permanent** — any `ErrorCode` not in `_FLEX_TRANSIENT_ERRORS` fails immediately. Safe default.
- **Constructor exceptions explicitly not retried** — documented rationale: `ib_async` has its own internal retry for Phase 1/Phase 2; if it raises to us, the error isn't transient at our level.
- **Token/query_id redaction preserved** — existing `exc_msg.replace()` logic unchanged in the exception branch.

### 4. Logging

| Event | Level | When |
|-------|-------|------|
| Transient error, retrying | WARNING | Each retry attempt |
| Success after retry | INFO | Succeeded on attempt 2+ |
| Permanent/unknown error | ERROR | Non-transient error code detected |
| Retries exhausted | ERROR | All 5 attempts returned 1019 |
| Malformed ErrorCode | WARNING | Non-integer ErrorCode in XML |

## Tests (14 new in `tests/ibkr/test_flex.py`)

Mock pattern: `monkeypatch.setattr(flex_client, "FlexReport", _FakeReport)` + `monkeypatch.setattr(flex_client.time, "sleep", lambda _: None)`.

### `_check_flex_error_response` unit tests

1. **`test_check_flex_error_response_detects_1019`** — error XML with `<ErrorCode>1019</ErrorCode>` → returns `(1019, "Statement generation in progress...")`
2. **`test_check_flex_error_response_valid_xml`** — normal FlexStatement XML (no ErrorCode) → returns `(None, None)`
3. **`test_check_flex_error_response_no_root`** — report object with no `root` attribute → returns `(None, None)`
4. **`test_check_flex_error_response_malformed_code`** — `<ErrorCode>abc</ErrorCode>` → returns `(None, None)`, logs warning
5. **`test_check_flex_error_response_nested_error_code`** — error XML where `<ErrorCode>` is nested inside an intermediate element (not a direct child of root) → validates the `.//ErrorCode` fallback path returns the correct `(code, msg)` tuple

### `_load_flex_report` retry tests

6. **`test_load_flex_report_retries_on_1019_then_succeeds`** — 1019 on attempt 1, valid report on attempt 2. Assert `call_count == 2`, report is not None, error is None.
7. **`test_load_flex_report_1019_exhausts_retries`** — 1019 on all 5 attempts → returns `(None, error)` with "1019" and "5 attempts" in message.
8. **`test_load_flex_report_permanent_error_no_retry`** — error code 1020 → `call_count == 1`, returns error with "1020".
9. **`test_load_flex_report_unknown_error_code_no_retry`** — error code 9999 (not in transient or permanent sets) → `call_count == 1`, treated as permanent.
10. **`test_load_flex_report_exception_not_retried`** — `FlexReport()` raises `ConnectionError` → no retry, returns error message.
11. **`test_load_flex_report_retry_delays`** — 1019 on all attempts, capture delays passed to `time.sleep` → asserts `[5, 10, 15, 20]`.
12. **`test_load_flex_report_token_redaction_in_error`** — `FlexReport()` raises exception containing the token string → error message has `***` not the raw token.
13. **`test_load_flex_report_query_id_redaction_in_error`** — `FlexReport()` raises exception containing the query_id string → error message has `***` not the raw query_id.

### Path loading + integration tests

14. **`test_load_flex_report_path_error_xml_detected`** — write error XML to a temp file, load via `path=` → returns `(None, error)` with error code in message.

## Verification

1. Run existing tests: `python -m pytest tests/ibkr/test_flex.py -v` (34 existing tests still pass)
2. Run new tests: `python -m pytest tests/ibkr/test_flex.py -v -k "error_response or retry or redaction or path_error"` (14 new tests pass)
3. Live test: `get_performance(mode="realized", source="ibkr_flex", use_cache=false)` — if IBKR returns 1019, should see retry WARNING logs and eventually get real data (or clear error after 5 attempts)
