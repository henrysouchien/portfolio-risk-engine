# IBKR Flex: Fix Phase 2 Polling (Own Download Implementation)

## Context

Our v1 retry fix (commit `17e0f0e6`) correctly detects error 1019 but retries by calling `FlexReport(token, queryId)` again — which restarts the entire Phase 1 + Phase 2 cycle from scratch. This doesn't work because:

1. `ib_async`'s `FlexReport.download()` Phase 2 checks `self.root[0].tag == "code"` to detect "still generating"
2. IBKR returns `<Status>Warn</Status>` as `root[0]` (not `<code>`), so the poll loop exits after **one 1-second poll**
3. Each of our retry attempts makes a fresh Phase 1 request → gets a new reference code → does one 1s poll → gets 1019 → gives up
4. IBKR actually needs ~6-9 seconds of polling on the same reference code to return data

**Fix**: Replace `FlexReport.download()` with our own Phase 1 + Phase 2 implementation that polls correctly, then set `report.data` and `report.root` directly.

## Files to Modify

| File | Change |
|------|--------|
| `ibkr/flex.py` | Replace `_load_flex_report()` download branch with `_download_flex_report()` that does its own Phase 1 + Phase 2 |
| `tests/ibkr/test_flex.py` | Update retry tests to match new behavior, add Phase 2 polling tests |

## Implementation

### 1. Add `_download_flex_report()` function (replaces the retry loop in `_load_flex_report`)

New function that implements both phases directly using `urllib.request.urlopen` (same as `ib_async` uses internally):

```python
def _download_flex_report(
    token: str,
    query_id: str,
    *,
    poll_interval: int = 3,
    poll_timeout: int = 60,
) -> tuple[Any | None, str | None]:
    """Download IBKR Flex report with correct Phase 2 polling.

    ib_async's FlexReport.download() has a bug: its Phase 2 poll loop checks
    root[0].tag == "code" but IBKR returns <Status> as root[0], so the loop
    exits after one 1-second poll. We implement both phases ourselves.

    Phase 1: POST token+queryId → get reference code + URL
    Phase 2: Poll reference URL every poll_interval seconds until data or timeout
    """
    from urllib.request import urlopen
    import xml.etree.ElementTree as ET

    # --- Phase 1: Request statement generation ---
    base_url = os.getenv(
        "IB_FLEXREPORT_URL",
        "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest?",
    )
    # Use urlencode for safe parameter encoding
    from urllib.parse import urlencode
    params = urlencode({"t": token, "q": query_id, "v": "3"})
    url = f"{base_url}{params}"

    try:
        resp = urlopen(url, timeout=30)
        data = resp.read()
        root = ET.fromstring(data)
    except Exception as exc:
        exc_msg = _redact_credentials(str(exc), token, query_id)
        return None, f"IBKR Flex Phase 1 request failed: {exc_msg}"

    status_el = root.find("Status")
    if status_el is None or (status_el.text or "").strip() != "Success":
        error_code_el = root.find("ErrorCode")
        error_msg_el = root.find("ErrorMessage")
        code = error_code_el.text if error_code_el is not None else "?"
        msg = error_msg_el.text if error_msg_el is not None else "unknown"
        return None, f"IBKR Flex Phase 1 error {code}: {msg}"

    ref_code_el = root.find("ReferenceCode")
    ref_url_el = root.find("Url")
    if ref_code_el is None or ref_url_el is None:
        return None, "IBKR Flex Phase 1 missing ReferenceCode or Url"

    ref_code = (ref_code_el.text or "").strip()
    ref_url = (ref_url_el.text or "").strip()
    if not ref_code or not ref_url:
        return None, "IBKR Flex Phase 1 returned empty ReferenceCode or Url"

    # --- Phase 2: Poll for statement ---
    logger.info("IBKR Flex statement requested (ref %s), polling...", ref_code)
    elapsed = 0

    while elapsed < poll_timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval

        poll_params = urlencode({"q": ref_code, "t": token, "v": "3"})
        poll_url = f"{ref_url}?{poll_params}"
        try:
            resp = urlopen(poll_url, timeout=30)
            poll_data = resp.read()
            poll_root = ET.fromstring(poll_data)
        except Exception as exc:
            exc_msg = _redact_credentials(str(exc), token, query_id)
            return None, f"IBKR Flex Phase 2 poll failed: {exc_msg}"

        # Check if still generating
        error_code, error_msg = _check_flex_error_response_xml(poll_root)
        if error_code == 1019:
            logger.info(
                "IBKR Flex still generating (ref %s, %ds elapsed)...",
                ref_code, elapsed,
            )
            continue

        if error_code is not None:
            # Non-transient error during polling
            return None, f"IBKR Flex Phase 2 error {error_code}: {error_msg}"

        # Got actual data — construct FlexReport object.
        # Use FlexReport() (no-args __init__ is a no-op) rather than
        # __new__ to be forward-compatible with future ib_async versions.
        report = FlexReport()
        report.data = poll_data
        report.root = poll_root
        logger.info(
            "IBKR Flex statement retrieved (ref %s, %ds elapsed, %d bytes)",
            ref_code, elapsed, len(poll_data),
        )
        return report, None

    return None, (
        f"IBKR Flex statement generation timed out after {poll_timeout}s "
        f"(ref {ref_code})"
    )
```

### 2. Add `_redact_credentials()` helper

```python
def _redact_credentials(msg: str, token: str, query_id: str) -> str:
    """Replace token/query_id in error messages with ***."""
    if token and token in msg:
        msg = msg.replace(token, "***")
    if query_id and query_id in msg:
        msg = msg.replace(query_id, "***")
    return msg
```

### 3. Add `_check_flex_error_response_xml()` (works on raw ElementTree root)

The existing `_check_flex_error_response()` takes a FlexReport object. We need a variant that works on a raw `xml.etree.ElementTree.Element` for use during Phase 2 polling before we have a FlexReport object:

```python
def _check_flex_error_response_xml(root: Any) -> tuple[int | None, str | None]:
    """Check raw XML root element for IBKR error response."""
    if root is None:
        return None, None
    error_code_el = root.find("ErrorCode")
    if error_code_el is None:
        error_code_el = root.find(".//ErrorCode")
    if error_code_el is None:
        return None, None
    try:
        code = int(error_code_el.text)
    except (TypeError, ValueError):
        # Malformed ErrorCode (non-integer) — log warning, treat as no error
        logger.warning(
            "IBKR Flex response contains non-integer ErrorCode: %r",
            getattr(error_code_el, "text", None),
        )
        return None, None
    message_el = root.find("ErrorMessage")
    if message_el is None:
        message_el = root.find(".//ErrorMessage")
    message = message_el.text if message_el is not None else f"IBKR Flex error {code}"
    return code, message
```

**Note**: The malformed ErrorCode warning logging is preserved in `_check_flex_error_response_xml` so existing test `test_check_flex_error_response_malformed_code` continues to pass unchanged.

Then refactor existing `_check_flex_error_response(report)` to delegate:

```python
def _check_flex_error_response(report: Any) -> tuple[int | None, str | None]:
    root = getattr(report, "root", None)
    return _check_flex_error_response_xml(root)
```

### 4. Simplify `_load_flex_report()` download branch

Replace the retry loop with a single call to `_download_flex_report()`:

```python
def _load_flex_report(
    *,
    token: str = "",
    query_id: str = "",
    path: Optional[str] = None,
) -> tuple[Any | None, str | None]:
    # --- Path loading (unchanged) ---
    if path:
        if not Path(path).exists():
            return None, f"IBKR Flex XML file not found: {path}"
        try:
            report = FlexReport(path=path)
        except Exception as exc:
            return None, f"Failed to load IBKR Flex XML from {path}: {exc}"
        error_code, error_msg = _check_flex_error_response(report)
        if error_code is not None:
            return None, f"IBKR Flex error {error_code} in {path}: {error_msg}"
        return report, None

    # --- Download ---
    if not token or not query_id:
        return None, "IBKR Flex credentials missing; skipping Flex download"

    return _download_flex_report(token, query_id)
```

### 5. Import changes

Add at top of file (some already present from v1):
- `import time` (already added in v1)
- `import xml.etree.ElementTree as ET` — needed inside `_download_flex_report` (or import locally)

Use local imports inside `_download_flex_report` for `urlopen`, `urlencode`, and `ET` to keep the module's top-level imports clean (matching `ib_async`'s own pattern).

### 6. Remove v1 retry constants/code

- Delete `_FLEX_TRANSIENT_ERRORS` constant (no longer needed — transient handling is inline in the Phase 2 poll loop)
- The retry loop in `_load_flex_report` is replaced entirely

## Tests

Update existing 14 tests + add new ones. Key changes:

### Tests to update
- **Retry tests (6-8, 10-11, 13)**: These tested the old retry-loop-around-FlexReport pattern. Update to test `_download_flex_report` Phase 1/Phase 2 behavior instead. Mock `urlopen` rather than `FlexReport`.

### New tests to add
1. **`test_download_phase1_success_phase2_immediate`** — Phase 1 returns Success+ref code, Phase 2 first poll returns data
2. **`test_download_phase2_polls_until_ready`** — Phase 2 returns 1019 twice then data on 3rd poll
3. **`test_download_phase2_timeout`** — Phase 2 returns 1019 until timeout → error with "timed out"
4. **`test_download_phase1_error`** — Phase 1 returns error (e.g. invalid token) → immediate failure
5. **`test_download_phase2_permanent_error`** — Phase 2 returns non-1019 error → immediate failure
6. **`test_download_phase1_network_error`** — urlopen raises on Phase 1 → error with redacted credentials
7. **`test_download_constructs_valid_flex_report`** — verify returned FlexReport has `.data` and `.root` set correctly
8. **`test_download_credential_redaction`** — token/query_id redacted in error messages

### Tests to keep as-is
- `_check_flex_error_response` tests (1-5) — still valid, helper is refactored but behavior identical
- Path loading test (14) — unchanged
- Exception-not-retried test (conceptually the same — Phase 1 exceptions aren't retried)

### Mock pattern
Instead of mocking `FlexReport`, mock `urllib.request.urlopen` to return canned XML responses for Phase 1 and Phase 2.

## Verification

1. Run tests: `python -m pytest tests/ibkr/test_flex.py -v`
2. Live test: `get_performance(mode="realized", source="ibkr_flex", use_cache=false)` after MCP reconnect
3. Confirm logs show: "IBKR Flex statement requested (ref XXXXX), polling..." → "still generating..." → "statement retrieved (Xs elapsed, N bytes)"
