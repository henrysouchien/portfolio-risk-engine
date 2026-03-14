# C4: Web App CSV Import + Normalizer Builder Integration

**Status**: Design complete — ready for review
**Owner**: TBD
**Created**: 2026-03-12

---

## Problem Statement

The web app CSV import (`CsvImportStep.tsx` → `POST /api/onboarding/preview-csv`) has two fundamental issues:

1. **Institution-first UX**: The UI nudges users to select an institution before uploading. Auto-detect exists in the backend but the frontend treats institution selection as the primary path.
2. **Dead-end on unknown formats**: When no normalizer matches, the backend returns `status: "needs_normalizer"` with a message pointing to filesystem paths and Python files — useful for Claude in MCP mode, useless for a web app user.

Meanwhile, an AI-driven normalizer builder exists in the finance-cli MCP server (9 tools + `normalizer_builder` skill) with a proven sample → analyze → stage → test → activate pipeline. But it targets **personal finance transactions** (Date/Description/Amount), not the schemas the web app needs.

## Current Architecture

### Three Normalizer Systems

| System | Location | Schema | Built-in | User dir | AI builder? |
|--------|----------|--------|----------|----------|-------------|
| **Position** normalizers | `inputs/normalizers/` | `NormalizeResult` (ticker/qty/value) | IBKR, Schwab | `~/.risk_module/normalizers/` | No |
| **Transaction** normalizers | `inputs/transaction_normalizers/` | `TransactionNormalizeResult` (FIFO trades/income/flows) | Schwab | `~/.risk_module/transaction_normalizers/` | No |
| **Finance-CLI** normalizers | finance-cli MCP server | Spending rows (Date/Description/Amount) | ~10 banks | `~/.finance_cli/normalizers/` | **Yes** (9 MCP tools) |

### Current CSV Import Flow (Web App)

```
CsvImportStep.tsx                routes/onboarding.py            mcp_tools/import_portfolio.py
┌──────────────┐    POST        ┌──────────────────┐            ┌─────────────────────┐
│ Select inst  │──────────────→ │ preview_csv()    │──────────→ │ import_portfolio()  │
│ Upload CSV   │  /preview-csv  │ write temp file  │            │ detect_and_normalize│
│ Show preview │←──────────────│ shape response   │←───────────│ or resolve brokerage│
│ Confirm      │    JSON        └──────────────────┘            └─────────────────────┘
└──────────────┘                                                         │
                                                                    No match?
                                                                         ↓
                                                                {status: "needs_normalizer",
                                                                 first_20_lines: [...],
                                                                 message: "Write a .py file..."}
                                                                         ↓
                                                                   Frontend shows error
                                                                   (DEAD END)
```

### Finance-CLI Normalizer Builder (Reference Architecture)

```
normalizer_sample_csv(file_path) → analyze headers → confirm with user
    → normalizer_stage(key, source) → normalizer_test(key, file_path)
    → fix if needed → normalizer_activate(key) → import
```

### Key Files

| File | Role |
|------|------|
| `routes/onboarding.py` | HTTP endpoints: `preview-csv`, `import-csv` |
| `mcp_tools/import_portfolio.py` | Position import MCP tool, `_needs_normalizer_response()` |
| `mcp_tools/import_transactions.py` | Transaction import MCP tool, `_needs_txn_normalizer_response()` |
| `inputs/normalizers/__init__.py` | Position normalizer registry + `detect_and_normalize()` |
| `inputs/transaction_normalizers/__init__.py` | Transaction normalizer registry |
| `inputs/normalizers/ibkr.py`, `inputs/normalizers/schwab.py` | Built-in position normalizers |
| `inputs/transaction_normalizers/schwab_csv.py` | Only built-in transaction normalizer |
| `inputs/transaction_normalizers/_example.py` | Reference template for user normalizers |
| `inputs/position_schema.py` | `NormalizeResult`, `PositionRecord` |
| `inputs/transaction_normalizer_schema.py` | `TransactionNormalizeResult` |
| `frontend/.../CsvImportStep.tsx` | Frontend CSV import component |
| `frontend/.../connectors/src/config/providers.ts` | `INSTITUTION_CONFIG` |
| `frontend/.../chat/ChatContext.tsx` | Shared chat state (`useSharedChat()`) |
| `routes/gateway_proxy.py` | Gateway proxy → Claude chat |

---

## Design Decisions

### Q1: Chat-driven vs Backend-autonomous vs Hybrid?

**Decision: Hybrid (chat-inline)**

| Approach | Pros | Cons |
|----------|------|------|
| **Chat-driven** (navigate to chat page) | Minimal new code, leverages existing gateway | Breaks import flow, user loses context |
| **Backend-autonomous** (REST endpoint calls LLM) | Seamless UX | Heavy new infra, needs LLM API in backend, security risks from generated code |
| **Hybrid** (inline chat panel in import flow) | Best UX, leverages gateway, stays in flow | More frontend work (manageable) |

**Rationale**: Normalizer building is inherently an AI task that requires conversation — analyzing headers, confirming column mappings, iterating on test failures. A pure REST API can't do this. But navigating away from the import flow is bad UX. The hybrid approach embeds a scoped chat panel directly in the import UI when `needs_normalizer` fires. The existing gateway proxy + `useSharedChat()` infrastructure already supports this.

### Q2: UX Flow

**Upload-first, institution-optional, with AI fallback:**

```
                                    ┌────────────────────────────┐
                                    │  1. Upload CSV             │
                                    │     (no institution needed)│
                                    └────────────┬───────────────┘
                                                 │
                                    ┌────────────▼───────────────┐
                                    │  2. Auto-detect format     │
                                    │     (backend)              │
                                    └────────┬───────┬───────────┘
                                             │       │
                                      matched     no match
                                             │       │
                                    ┌────────▼──┐  ┌─▼──────────────────┐
                                    │ 3a. Show  │  │ 3b. "Format not    │
                                    │ preview   │  │  recognized" panel │
                                    │ → confirm │  │                    │
                                    └───────────┘  │ Options:           │
                                                   │ • Select inst      │
                                                   │   (retry w/ hint)  │
                                                   │ • "Build with AI"  │
                                                   │   → inline chat    │
                                                   └──────┬─────────────┘
                                                          │
                                              ┌───────────▼────────────┐
                                              │ 4. Inline chat panel   │
                                              │ Claude analyzes CSV,   │
                                              │ confirms columns w/    │
                                              │ user, generates        │
                                              │ normalizer, tests it   │
                                              └───────────┬────────────┘
                                                          │
                                              ┌───────────▼────────────┐
                                              │ 5. Auto-retry import   │
                                              │ → preview → confirm    │
                                              └────────────────────────┘
```

### Q3: Gateway Routing

**No new gateway routing needed.** The existing gateway proxy routes chat messages to the Claude gateway, which has access to portfolio-mcp tools. The normalizer builder will be new MCP tools registered in portfolio-mcp, accessible through the same gateway path.

The chat panel needs:
- A pre-populated first message containing CSV context (first 20 lines, filename, detected headers)
- The normalizer builder to use portfolio-mcp MCP tools (new tools, see Phase 2)

The gateway already handles tool approval flows via `GatewayClaudeService.ts`.

### Q4: Which Normalizer Schema?

The web app import currently handles **positions** only. Phase 1 focuses on position normalizers. Transaction normalizer builder can follow the same pattern in a later phase.

**Position normalizer output** (`NormalizeResult` from `inputs/position_schema.py`):
```python
@dataclass
class NormalizeResult:
    positions: list[PositionRecord]  # ticker, name, quantity, value, type, currency, ...
    errors: list[str]
    warnings: list[str]
    brokerage_name: str
    skipped_rows: int = 0
    base_currency: str = "USD"
```

### Q5: Where Do Built Normalizers Live?

**Filesystem** (`~/.risk_module/normalizers/`), same as today. This is a single-user system. No DB-backed normalizer registry needed.

The finance-cli staging pattern (stage → test → activate) prevents broken normalizers from polluting the active directory. We replicate this:
- Staging: `~/.risk_module/normalizers/.staging/{key}.py`
- Active: `~/.risk_module/normalizers/{key}.py`

---

## Implementation Plan

### Phase 1: Upload-First UX + Rich `needs_normalizer` Response

**Goal**: File upload is primary, institution optional. `needs_normalizer` shows actionable UI instead of a dead-end error.

**Can run in parallel with**: Phase 2.

---

#### Step 1.1 — Add `_detect_likely_headers()` and `_find_header_line()` to import_portfolio

**File**: `mcp_tools/import_portfolio.py`

Add two private helpers above `_needs_normalizer_response()`:

```python
import csv
import io

_HEADER_KEYWORDS = {
    "ticker", "symbol", "name", "description", "quantity", "qty", "shares",
    "value", "amount", "price", "cost", "currency", "account", "type",
    "market_value", "current_value", "last_price", "close", "isin", "cusip",
    "sedol", "exchange", "weight", "allocation", "sector",
}


def _find_header_line(lines: list[str], max_scan: int = 10) -> int | None:
    """Return the 0-based index of the most likely header row, or None."""
    best_idx: int | None = None
    best_score = 0
    for idx, line in enumerate(lines[:max_scan]):
        try:
            cells = next(csv.reader(io.StringIO(line)))
        except Exception:
            continue
        if len(cells) < 2:
            continue
        score = sum(
            1 for cell in cells
            if cell.strip().lower().replace(" ", "_") in _HEADER_KEYWORDS
        )
        non_numeric = sum(
            1 for cell in cells
            if cell.strip() and not _is_numeric(cell.strip())
        )
        total_score = score + (non_numeric * 0.3)
        if total_score > best_score and non_numeric >= len(cells) * 0.5:
            best_score = total_score
            best_idx = idx
    return best_idx


def _is_numeric(value: str) -> bool:
    try:
        float(value.replace(",", "").replace("$", "").replace("%", ""))
        return True
    except ValueError:
        return False


def _detect_likely_headers(lines: list[str]) -> list[str]:
    """Return column names from the detected header row, or empty list."""
    idx = _find_header_line(lines)
    if idx is None:
        return []
    try:
        cells = next(csv.reader(io.StringIO(lines[idx])))
        return [cell.strip() for cell in cells if cell.strip()]
    except Exception:
        return []
```

Then update `_needs_normalizer_response()` (replace the existing function body entirely):

```python
def _needs_normalizer_response(lines: list[str], brokerage: str) -> dict[str, Any]:
    requested = str(brokerage or "").strip()
    message = "No normalizer matched this CSV format."
    if requested:
        message = f"No normalizer matched requested brokerage {requested!r}."
    return {
        "status": "needs_normalizer",
        "first_20_lines": lines[:_FIRST_20_LINES],
        "row_count": len(lines),
        "detected_headers": _detect_likely_headers(lines),
        "header_line_index": _find_header_line(lines),
        "message": message,
    }
```

**Do NOT** change any other function in this file. The `import csv` and `import io` may already be imported — check first.

---

#### Step 1.2 — Forward new fields in `_shape_csv_error()`

**File**: `routes/onboarding.py`

In `_shape_csv_error()` (line ~161), add forwarding for the two new fields. Insert after the existing `if "first_20_lines" in result:` block:

```python
    if "detected_headers" in result:
        payload["detected_headers"] = list(result.get("detected_headers") or [])
    if "header_line_index" in result:
        payload["header_line_index"] = result.get("header_line_index")
```

**Do NOT** change any other function in this file.

---

#### Step 1.3 — Update `CsvPreviewResponse` type and `CsvImportStep` layout

**File**: `frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx`

**1. Update the `CsvPreviewResponse` interface** (line ~16):

Add two new optional fields:

```typescript
export interface CsvPreviewResponse {
  status: 'success' | 'error' | 'needs_normalizer';
  positions_count?: number;
  total_value?: number;
  sample_holdings?: Array<{
    ticker: string;
    shares: number;
    value: number;
  }>;
  warnings?: string[];
  source_key?: string;
  message?: string;
  errors?: string[];
  first_20_lines?: string[];
  row_count?: number;                // already forwarded by _shape_csv_error
  detected_headers?: string[];       // NEW
  header_line_index?: number | null; // NEW — null when no header detected
}
```

**2. Add a `needsNormalizer` state variable** alongside the existing state:

```typescript
const [needsNormalizerData, setNeedsNormalizerData] = useState<CsvPreviewResponse | null>(null);
```

**3. Update `requestPreview`**: After the `api.request` call, handle `needs_normalizer` as a distinct path (not just an error):

```typescript
if (response.status === 'needs_normalizer') {
  setNeedsNormalizerData(response);
  setErrorMessage(null);
  setPreview(null);
  return;
}
```

**State cleanup rules** (add to `requestPreview` and event handlers):
- On `requestPreview` start: clear `needsNormalizerData`, `errorMessage`, `preview`
- On new file selection (`handleFileChange`): clear all of the above plus `institution`, then call `requestPreview(nextFile, '')` with empty institution (prevents stale institution from forcing wrong normalizer on retry)
- On success: clear `needsNormalizerData`

> Phase 3 extends these rules: `requestPreview` start also clears `showBuilder` and `stagedFilePath`. A new `handleNormalizerActivated` handler clears `needsNormalizerData`, `showBuilder`, `stagedFilePath`, `institution`, then re-runs `requestPreview(selectedFile, '')`. See Step 3.3.

**4. Reorder the layout** — file upload section moves above institution section. Institution section gets a label like "Override format detection (optional)" and is collapsed by default. Expand via a `useState<boolean>` toggle ("Can't auto-detect? Select institution manually").

**5. Render `needs_normalizer` state** between the error block and the success preview block:

```tsx
{needsNormalizerData ? (
  <Card className="border border-amber-200 shadow-none">
    <CardHeader className="space-y-2">
      <CardTitle className="text-base text-amber-900">
        Format not recognized
      </CardTitle>
      <p className="text-sm text-neutral-600">
        We couldn't auto-detect the format of this CSV.
      </p>
    </CardHeader>
    <CardContent className="space-y-4">
      {needsNormalizerData.detected_headers?.length ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-neutral-700">Detected columns</p>
          <div className="flex flex-wrap gap-1.5">
            {needsNormalizerData.detected_headers.map(h => (
              <span key={h} className="rounded-md bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700">
                {h}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {needsNormalizerData.first_20_lines?.length ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-neutral-700">Sample rows</p>
          <pre className="max-h-40 overflow-auto rounded-md bg-neutral-50 p-3 text-xs text-neutral-600">
            {needsNormalizerData.first_20_lines.slice(0, 6).join('\n')}
          </pre>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowInstitutionSelector(true)}
        >
          Select institution manually
        </Button>
        <Button
          variant="premium"
          size="sm"
          disabled
          title="Coming soon"
        >
          Build with AI
        </Button>
      </div>
    </CardContent>
  </Card>
) : null}
```

The "Build with AI" button is rendered **disabled** with "Coming soon" tooltip — Phase 3 wires it up. The "Select institution manually" button expands the institution selector and re-runs preview.

**Do NOT** modify `useOnboardingActivation.ts`, `OnboardingWizard.tsx`, or any file outside the ones listed.

---

#### Step 1.4 — Update `CsvImportCompletionResponse` type

**File**: `frontend/packages/ui/src/components/onboarding/useOnboardingActivation.ts`

Add the same two new fields to the `CsvImportCompletionResponse` type (line ~39):

```typescript
interface CsvImportCompletionResponse {
  status: 'success' | 'error' | 'needs_normalizer';
  message?: string;
  warnings?: string[];
  positions_count?: number;
  portfolio_data?: Portfolio;
  portfolio_name?: string;
  first_20_lines?: string[];         // already forwarded by _shape_csv_error
  row_count?: number;                // already forwarded by _shape_csv_error
  detected_headers?: string[];       // NEW
  header_line_index?: number | null; // NEW — null when no header detected
}
```

**Do NOT** change any logic in this file — type-only change.

---

#### Step 1.5 — Tests

**File**: `tests/mcp_tools/test_import_portfolio.py`

Add tests after the existing `test_needs_normalizer_response_when_no_normalizer_matches`:

```python
def test_detect_likely_headers_with_standard_csv(monkeypatch, tmp_path):
    """Header row with recognizable column names is detected."""
    csv_content = "Symbol,Name,Quantity,Value,Currency\nAAPL,Apple,100,17200,USD\n"
    csv_file = tmp_path / "standard.csv"
    csv_file.write_text(csv_content)
    monkeypatch.setattr("mcp_tools.import_portfolio.detect_and_normalize", lambda *a: None)
    out = import_portfolio_tool.import_portfolio(file_path=str(csv_file), brokerage="", dry_run=True)
    assert out["status"] == "needs_normalizer"
    assert "Symbol" in out["detected_headers"]
    assert "Quantity" in out["detected_headers"]
    assert out["header_line_index"] == 0


def test_detect_likely_headers_with_preamble(monkeypatch, tmp_path):
    """Header row preceded by junk lines is still found."""
    csv_content = "Report generated 2026-03-12\nAccount: XYZ\nTicker,Shares,Market Value\nAAPL,100,17200\n"
    csv_file = tmp_path / "preamble.csv"
    csv_file.write_text(csv_content)
    monkeypatch.setattr("mcp_tools.import_portfolio.detect_and_normalize", lambda *a: None)
    out = import_portfolio_tool.import_portfolio(file_path=str(csv_file), brokerage="", dry_run=True)
    assert out["status"] == "needs_normalizer"
    assert out["header_line_index"] == 2
    assert "Ticker" in out["detected_headers"]


def test_detect_likely_headers_no_headers(monkeypatch, tmp_path):
    """Pure numeric CSV returns empty detected_headers."""
    csv_content = "1,2,3\n4,5,6\n"
    csv_file = tmp_path / "numbers.csv"
    csv_file.write_text(csv_content)
    monkeypatch.setattr("mcp_tools.import_portfolio.detect_and_normalize", lambda *a: None)
    out = import_portfolio_tool.import_portfolio(file_path=str(csv_file), brokerage="", dry_run=True)
    assert out["status"] == "needs_normalizer"
    assert out["detected_headers"] == []
    assert out["header_line_index"] is None


def test_needs_normalizer_response_includes_detected_headers(monkeypatch, tmp_path):
    """needs_normalizer response has detected_headers and header_line_index keys."""
    csv_content = "Account,Symbol,Description,Qty,Price,Value\nZ123,AAPL,Apple,100,172,17200\n"
    csv_file = tmp_path / "fidelity.csv"
    csv_file.write_text(csv_content)
    monkeypatch.setattr("mcp_tools.import_portfolio.detect_and_normalize", lambda *a: None)
    out = import_portfolio_tool.import_portfolio(file_path=str(csv_file), brokerage="", dry_run=True)
    assert out["status"] == "needs_normalizer"
    assert isinstance(out["detected_headers"], list)
    assert isinstance(out.get("header_line_index"), int)
    assert "first_20_lines" in out
```

**Run with**: `pytest tests/mcp_tools/test_import_portfolio.py -x -q`

---

### Phase 2: Position Normalizer Builder MCP Tools

**Goal**: 5 new tools in portfolio-mcp implementing the stage → test → activate pipeline for position normalizers.

**Can run in parallel with**: Phase 1.

---

#### Step 2.0 — Fix `_all_normalizers()` DB-mode gate (BLOCKER)

**File**: `inputs/normalizers/__init__.py`

The current `_all_normalizers()` deliberately skips user normalizers when `is_db_available()` is true (line 42-48). The web app always has DB, so activated normalizers in `~/.risk_module/normalizers/` are never discovered. This breaks the entire normalizer builder flow.

**Replace the existing `_all_normalizers()` function** (lines 42-48):

```python
def _all_normalizers() -> list[NormalizerModule]:
    """Return built-ins plus user normalizers.

    User normalizers from ~/.risk_module/normalizers/ are always loaded
    so that normalizers created via the normalizer builder are discoverable
    by detect_and_normalize() in both DB and no-DB modes.
    """
    return [*BUILT_IN, *_load_user_normalizers()]
```

Also update `_load_user_normalizers()` to skip `.staging/` subdirectory files — the staging dir lives inside the normalizers dir and its contents should not be auto-loaded:

```python
def _load_user_normalizers() -> list[NormalizerModule]:
    """Load user-authored normalizers from ~/.risk_module/normalizers/."""
    user_dir = Path.home() / ".risk_module" / "normalizers"
    if not user_dir.is_dir():
        return []

    normalizers: list[NormalizerModule] = []
    for py_file in sorted(user_dir.glob("*.py")):  # glob("*.py") only matches top-level, not subdirs
        if py_file.name.startswith("_"):
            continue
        # ... rest unchanged
```

Note: `user_dir.glob("*.py")` already only matches top-level files (not `user_dir.glob("**/*.py")`), so `.staging/` subdirectory files are naturally excluded. No code change needed for this — just verify the existing glob is `"*.py"` not `"**/*.py"`.

**Add a test** to `tests/mcp_tools/test_normalizer_builder.py` (covered in Step 2.3).

**Do NOT** change `_load_user_normalizers()` logic beyond removing the DB gate. **Do NOT** touch `inputs/transaction_normalizers/__init__.py` (it already always loads user normalizers).

**Existing test updates required** in `tests/inputs/test_normalizers.py`:

Two tests explicitly verify the DB-gate behavior and will fail after this change:

1. **`test_user_normalizers_are_not_scanned_when_db_is_available`** (line 157): Asserts that `_all_normalizers()` returns only `BUILT_IN` when DB is available. **Delete this test** — the behavior it tests is being intentionally removed.

2. **`test_user_normalizer_loading_from_user_directory`** (line 118): Sets `is_db_available` to `False`. **Remove the `monkeypatch.setattr(database, "is_db_available", lambda: False)` line** — user normalizers now load regardless of DB state, so this mock is unnecessary (but the rest of the test remains valid).

3. **`test_malformed_user_normalizer_missing_detect_is_skipped_with_warning`** (line 187): Same — **remove the `monkeypatch.setattr(database, "is_db_available", lambda: False)` line**.

4. **`test_registry_returns_none_for_unrecognized_csv`**: After the DB gate removal, `_all_normalizers()` always loads user normalizers from `Path.home() / ".risk_module" / "normalizers"`. Without HOME isolation, this test will scan the real HOME directory and may pick up user-authored normalizers that match its test CSV, causing non-deterministic failures. **Add `monkeypatch.setenv("HOME", str(tmp_path))`** (using a `tmp_path` parameter) so `_load_user_normalizers()` finds an empty directory.

**Verify with**: `pytest tests/inputs/test_normalizers.py -x -q`

---

#### Step 2.1 — Create `mcp_tools/normalizer_builder.py`

**File**: `mcp_tools/normalizer_builder.py` **(NEW)**

```python
"""Normalizer builder tools — stage, test, activate position/transaction normalizers."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from inputs.position_schema import NormalizeResult, PositionRecord
from mcp_tools.common import handle_mcp_errors

_SAFE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Directories by normalizer type
_DIRS: dict[str, Path] = {
    "position": Path.home() / ".risk_module" / "normalizers",
    "transaction": Path.home() / ".risk_module" / "transaction_normalizers",
}


def _resolve_dirs(normalizer_type: str) -> tuple[Path, Path]:
    """Return (active_dir, staging_dir) for the given type."""
    base = _DIRS.get(normalizer_type)
    if base is None:
        raise ValueError(f"Unknown normalizer_type: {normalizer_type!r}. Must be 'position' or 'transaction'.")
    staging = base / ".staging"
    return base, staging


def _validate_key(key: str) -> None:
    if not _SAFE_KEY_PATTERN.match(key):
        raise ValueError(
            f"Invalid normalizer key {key!r}. Must match [a-z][a-z0-9_]{{0,63}}."
        )


def _load_module(py_path: Path) -> ModuleType:
    """Dynamically load a Python module from a file path."""
    module_name = f"normalizer_builder_{py_path.stem}_{py_path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create import spec for {py_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_position_result(result: Any, detect_result: bool) -> list[str]:
    """Validate that result looks like a NormalizeResult suitable for import_portfolio.

    Uses duck-typing checks (hasattr/to_dict) rather than isinstance — this
    mirrors how import_portfolio itself consumes the result. Checks:
    - detect() returned True (required for auto-detect to find the normalizer)
    - result has .positions list where each entry has .to_dict() and .ticker (not plain dicts)
    - result.errors is empty (import is all-or-nothing per position_schema.py)
    - brokerage_name is set
    """
    errors: list[str] = []
    if not detect_result:
        errors.append("detect() returned False — auto-detect will not find this normalizer.")
    if not hasattr(result, "positions"):
        errors.append("Result missing 'positions' attribute.")
        return errors
    if not isinstance(result.positions, list):
        errors.append(f"'positions' is {type(result.positions).__name__}, expected list.")
        return errors
    if len(result.positions) == 0:
        errors.append("'positions' list is empty — normalizer produced no positions.")
    for i, pos in enumerate(result.positions):
        if not hasattr(pos, "to_dict"):
            errors.append(
                f"Position {i}: must be a PositionRecord instance with to_dict(), "
                f"got {type(pos).__name__}. Use PositionRecord(...) from inputs.position_schema."
            )
            continue
        ticker = getattr(pos, "ticker", None)
        if not ticker:
            errors.append(f"Position {i}: missing or empty 'ticker'.")
    # Check result.errors — import_portfolio rejects if any errors exist
    result_errors = list(getattr(result, "errors", []))
    if result_errors:
        errors.append(
            f"Normalizer reported {len(result_errors)} error(s): {'; '.join(result_errors[:3])}"
        )
    if not getattr(result, "brokerage_name", None):
        errors.append("Result missing or empty 'brokerage_name'.")
    return errors


@handle_mcp_errors
def normalizer_sample_csv(
    file_path: str = "",
    lines: int = 20,
) -> dict[str, Any]:
    """Read the first N lines of a CSV file for normalizer analysis."""
    if not file_path:
        return {"status": "error", "error": "file_path is required."}
    path = Path(file_path).expanduser()
    if not path.is_file():
        return {"status": "error", "error": f"File not found: {file_path}"}
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "status": "ok",
        "lines": raw_lines[:lines],
        "total_lines": len(raw_lines),
        "filename": path.name,
    }


@handle_mcp_errors
def normalizer_stage(
    key: str = "",
    source: str = "",
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict[str, Any]:
    """Write a normalizer module to the staging directory. Must test before activating."""
    if not key:
        return {"status": "error", "error": "key is required."}
    if not source:
        return {"status": "error", "error": "source is required."}
    _validate_key(key)
    _base, staging = _resolve_dirs(normalizer_type)
    staging.mkdir(parents=True, exist_ok=True)
    staged_path = staging / f"{key}.py"
    staged_path.write_text(source, encoding="utf-8")
    # Clear stale .tested marker — restaged code must be re-tested
    tested_marker = staging / f"{key}.tested"
    tested_marker.unlink(missing_ok=True)
    return {
        "status": "ok",
        "key": key,
        "normalizer_type": normalizer_type,
        "staged_path": str(staged_path),
    }


@handle_mcp_errors
def normalizer_test(
    key: str = "",
    file_path: str = "",
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict[str, Any]:
    """Load a staged normalizer, run it against a CSV, and validate the output."""
    if not key:
        return {"status": "error", "error": "key is required."}
    if not file_path:
        return {"status": "error", "error": "file_path is required."}
    _validate_key(key)
    _base, staging = _resolve_dirs(normalizer_type)
    staged_path = staging / f"{key}.py"
    if not staged_path.is_file():
        return {"status": "error", "error": f"No staged normalizer found: {staged_path}"}

    # Load the module
    module = _load_module(staged_path)

    # Validate interface
    if not callable(getattr(module, "detect", None)):
        return {"status": "error", "error": "Module missing callable detect() function."}
    if not callable(getattr(module, "normalize", None)):
        return {"status": "error", "error": "Module missing callable normalize() function."}

    # Read CSV
    csv_path = Path(file_path).expanduser()
    if not csv_path.is_file():
        return {"status": "error", "error": f"CSV file not found: {file_path}"}
    lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()

    # Run detect()
    detect_result = bool(module.detect(lines))

    # Run normalize()
    result = module.normalize(lines, csv_path.name)

    # Validate output
    if normalizer_type == "position":
        validation_errors = _validate_position_result(result, detect_result)
    else:
        # Transaction validation — check for fifo_transactions attribute
        validation_errors = []
        if not hasattr(result, "fifo_transactions"):
            validation_errors.append("Result missing 'fifo_transactions' attribute.")

    # Build sample for position type — guard against malformed positions (None, dict, etc.)
    sample_positions: list[dict[str, Any]] = []
    positions_list = getattr(result, "positions", None)
    if not isinstance(positions_list, list):
        positions_list = []
    if normalizer_type == "position":
        for pos in positions_list[:5]:
            if hasattr(pos, "to_dict"):
                sample_positions.append(pos.to_dict())
            elif isinstance(pos, dict):
                sample_positions.append(pos)

    passed = not validation_errors

    # Write .tested marker on success so normalizer_activate() can verify
    if passed:
        tested_marker = staging / f"{key}.tested"
        tested_marker.write_text("ok", encoding="utf-8")
    else:
        # Remove stale marker if test fails after a prior pass
        tested_marker = staging / f"{key}.tested"
        tested_marker.unlink(missing_ok=True)

    return {
        "status": "ok" if passed else "error",
        "key": key,
        "normalizer_type": normalizer_type,
        "detect_result": detect_result,
        "positions_count": len(positions_list),
        "sample_positions": sample_positions,
        "warnings": list(getattr(result, "warnings", [])),
        "errors": list(getattr(result, "errors", [])),
        "validation_errors": validation_errors,
        "brokerage_name": getattr(result, "brokerage_name", ""),
    }


@handle_mcp_errors
def normalizer_activate(
    key: str = "",
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict[str, Any]:
    """Move a tested staged normalizer to the active directory.

    Requires a .tested marker file created by normalizer_test() on success.
    This prevents activating a normalizer that was never tested or that failed testing.
    """
    if not key:
        return {"status": "error", "error": "key is required."}
    _validate_key(key)
    base, staging = _resolve_dirs(normalizer_type)
    staged_path = staging / f"{key}.py"
    if not staged_path.is_file():
        return {"status": "error", "error": f"No staged normalizer found for key {key!r}."}
    tested_marker = staging / f"{key}.tested"
    if not tested_marker.is_file():
        return {
            "status": "error",
            "error": f"Normalizer {key!r} has not passed testing. Run normalizer_test() first.",
        }
    active_path = base / f"{key}.py"
    staged_path.rename(active_path)
    tested_marker.unlink(missing_ok=True)
    return {
        "status": "ok",
        "key": key,
        "normalizer_type": normalizer_type,
        "active_path": str(active_path),
    }


@handle_mcp_errors
def normalizer_list(
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict[str, Any]:
    """List active and staged normalizers."""
    base, staging = _resolve_dirs(normalizer_type)
    active: list[str] = []
    staged: list[str] = []
    if base.is_dir():
        active = sorted(
            p.stem for p in base.glob("*.py")
            if not p.name.startswith("_")
        )
    if staging.is_dir():
        staged = sorted(
            p.stem for p in staging.glob("*.py")
            if not p.name.startswith("_")
        )
    return {
        "status": "ok",
        "normalizer_type": normalizer_type,
        "active": active,
        "staged": staged,
        "active_dir": str(base),
        "staging_dir": str(staging),
    }
```

---

#### Step 2.2 — Register tools in `mcp_server.py`

**File**: `mcp_server.py`

**Add imports**. The `Literal` import already exists in `mcp_server.py` (used by `get_positions` etc.). Add after the existing `from mcp_tools.*` import block (around line ~188):

```python
from mcp_tools.normalizer_builder import normalizer_sample_csv as _normalizer_sample_csv
from mcp_tools.normalizer_builder import normalizer_stage as _normalizer_stage
from mcp_tools.normalizer_builder import normalizer_test as _normalizer_test
from mcp_tools.normalizer_builder import normalizer_activate as _normalizer_activate
from mcp_tools.normalizer_builder import normalizer_list as _normalizer_list
```

**Add 5 tool wrappers**. Place them after the existing `import_portfolio` tool definition. Follow the exact pattern used by other tools:

```python
@mcp.tool()
def normalizer_sample_csv(
    file_path: str = "",
    lines: int = 20,
) -> dict:
    """
    Read the first N lines of a CSV file for normalizer analysis.

    Use this as the first step when building a normalizer for an unknown CSV format.
    Returns the raw lines so you can identify headers, column structure, and data patterns.

    Args:
        file_path: Absolute path to the CSV file.
        lines: Number of lines to read (default 20).

    Returns:
        Raw lines, total line count, and filename.

    Examples:
        "Sample the CSV I uploaded" -> normalizer_sample_csv(file_path="/tmp/normalizer_builder/abc.csv")
    """
    return _normalizer_sample_csv(file_path=file_path, lines=lines)


@mcp.tool()
def normalizer_stage(
    key: str = "",
    source: str = "",
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict:
    """
    Write a normalizer Python module to the staging directory.

    The module must define detect(lines) -> bool and normalize(lines, filename) -> NormalizeResult.
    For position normalizers, NormalizeResult must have a .positions list of PositionRecord objects.
    Each PositionRecord needs: ticker (str), quantity (float), value (float), type (PositionType),
    currency (str or None for cash). Use `from inputs.position_schema import NormalizeResult, PositionRecord, PositionType`.

    Always call normalizer_test() after staging to validate before activating.

    Args:
        key: Normalizer identifier (lowercase, alphanumeric + underscore, e.g. "fidelity").
        source: Full Python source code for the normalizer module.
        normalizer_type: "position" for position normalizers (default), "transaction" for transaction normalizers.

    Returns:
        Staged file path on success.

    Examples:
        "Stage the fidelity normalizer" -> normalizer_stage(key="fidelity", source="...")
    """
    return _normalizer_stage(key=key, source=source, normalizer_type=normalizer_type)


@mcp.tool()
def normalizer_test(
    key: str = "",
    file_path: str = "",
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict:
    """
    Test a staged normalizer against a CSV file.

    Loads the staged module, runs detect() and normalize(), validates the output
    matches the expected schema. Returns sample positions, validation errors, and warnings.

    Args:
        key: Normalizer identifier (must be staged first).
        file_path: Path to the CSV file to test against.
        normalizer_type: "position" or "transaction".

    Returns:
        detect_result, positions_count, sample_positions, validation_errors, warnings, errors.

    Examples:
        "Test the fidelity normalizer" -> normalizer_test(key="fidelity", file_path="/tmp/abc.csv")
    """
    return _normalizer_test(key=key, file_path=file_path, normalizer_type=normalizer_type)


@mcp.tool()
def normalizer_activate(
    key: str = "",
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict:
    """
    Activate a previously tested staged normalizer.

    Moves the normalizer from the staging directory to the active directory.
    After activation, the normalizer will be auto-discovered by detect_and_normalize()
    on subsequent CSV imports.

    Only call this after normalizer_test() returns status "ok".

    Args:
        key: Normalizer identifier.
        normalizer_type: "position" or "transaction".

    Returns:
        Active file path on success.

    Examples:
        "Activate the fidelity normalizer" -> normalizer_activate(key="fidelity")
    """
    return _normalizer_activate(key=key, normalizer_type=normalizer_type)


@mcp.tool()
def normalizer_list(
    normalizer_type: Literal["position", "transaction"] = "position",
) -> dict:
    """
    List active and staged normalizers.

    Args:
        normalizer_type: "position" or "transaction".

    Returns:
        Lists of active and staged normalizer keys, plus directory paths.

    Examples:
        "What normalizers are available?" -> normalizer_list()
        "Show transaction normalizers" -> normalizer_list(normalizer_type="transaction")
    """
    return _normalizer_list(normalizer_type=normalizer_type)
```

**Do NOT** modify any existing tool definitions or imports.

---

#### Step 2.3 — Tests

**File**: `tests/mcp_tools/test_normalizer_builder.py` **(NEW)**

```python
"""Tests for mcp_tools/normalizer_builder.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mcp_tools.normalizer_builder import (
    normalizer_activate,
    normalizer_list,
    normalizer_sample_csv,
    normalizer_stage,
    normalizer_test,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CSV = "Symbol,Name,Quantity,Value,Currency\nAAPL,Apple Inc,100,17200.00,USD\nVTI,Vanguard Total,50,12265.00,USD\n"

VALID_NORMALIZER_SOURCE = textwrap.dedent("""\
    from inputs.position_schema import NormalizeResult, PositionRecord, PositionType

    BROKERAGE_NAME = "Test Broker"

    def detect(lines):
        for line in lines[:3]:
            if "Symbol" in line and "Quantity" in line and "Value" in line:
                return True
        return False

    def normalize(lines, filename):
        import csv, io
        header_idx = 0
        for i, line in enumerate(lines[:5]):
            if "Symbol" in line:
                header_idx = i
                break
        reader = csv.DictReader(io.StringIO("\\n".join(lines[header_idx:])))
        positions = []
        for row in reader:
            positions.append(PositionRecord(
                ticker=row["Symbol"],
                name=row.get("Name", ""),
                quantity=float(row["Quantity"]),
                value=float(row["Value"]),
                type=PositionType.EQUITY,
                currency=row.get("Currency", "USD"),
            ))
        return NormalizeResult(
            positions=positions,
            errors=[],
            warnings=[],
            brokerage_name=BROKERAGE_NAME,
        )
""")

BAD_NORMALIZER_NO_DETECT = textwrap.dedent("""\
    def normalize(lines, filename):
        return None
""")


@pytest.fixture()
def staging_dir(monkeypatch, tmp_path):
    """Redirect normalizer dirs AND Path.home() to tmp_path.

    This ensures both normalizer_builder tools (via _DIRS) and
    _load_user_normalizers() (via Path.home()) see the same directory.
    """
    pos_dir = tmp_path / ".risk_module" / "normalizers"
    pos_dir.mkdir(parents=True)
    staging = pos_dir / ".staging"
    staging.mkdir()
    monkeypatch.setattr(
        "mcp_tools.normalizer_builder._DIRS",
        {"position": pos_dir, "transaction": tmp_path / ".risk_module" / "transaction_normalizers"},
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def sample_csv_file(tmp_path):
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text(SAMPLE_CSV)
    return csv_file


# ---------------------------------------------------------------------------
# normalizer_sample_csv
# ---------------------------------------------------------------------------

def test_normalizer_sample_csv_returns_lines(sample_csv_file):
    out = normalizer_sample_csv(file_path=str(sample_csv_file), lines=10)
    assert out["status"] == "ok"
    assert len(out["lines"]) == 3
    assert out["total_lines"] == 3
    assert out["filename"] == "sample.csv"


def test_normalizer_sample_csv_missing_file():
    out = normalizer_sample_csv(file_path="/nonexistent/file.csv")
    assert out["status"] == "error"


# ---------------------------------------------------------------------------
# normalizer_stage
# ---------------------------------------------------------------------------

def test_normalizer_stage_writes_to_staging_dir(staging_dir):
    out = normalizer_stage(key="test_broker", source=VALID_NORMALIZER_SOURCE)
    assert out["status"] == "ok"
    assert out["key"] == "test_broker"
    staged_path = Path(out["staged_path"])
    assert staged_path.exists()
    assert staged_path.read_text() == VALID_NORMALIZER_SOURCE


def test_normalizer_stage_rejects_unsafe_key(staging_dir):
    out = normalizer_stage(key="../evil", source="x")
    assert out["status"] == "error"


def test_normalizer_stage_rejects_uppercase_key(staging_dir):
    out = normalizer_stage(key="TestBroker", source="x")
    assert out["status"] == "error"


# ---------------------------------------------------------------------------
# normalizer_test
# ---------------------------------------------------------------------------

def test_normalizer_test_validates_output_schema(staging_dir, sample_csv_file):
    normalizer_stage(key="test_broker", source=VALID_NORMALIZER_SOURCE)
    out = normalizer_test(key="test_broker", file_path=str(sample_csv_file))
    assert out["status"] == "ok"
    assert out["detect_result"] is True
    assert out["positions_count"] == 2
    assert len(out["sample_positions"]) == 2
    assert out["validation_errors"] == []
    assert out["brokerage_name"] == "Test Broker"


def test_normalizer_test_returns_sample_positions(staging_dir, sample_csv_file):
    normalizer_stage(key="test_broker", source=VALID_NORMALIZER_SOURCE)
    out = normalizer_test(key="test_broker", file_path=str(sample_csv_file))
    first = out["sample_positions"][0]
    assert first["ticker"] == "AAPL"
    assert first["quantity"] == 100
    assert first["value"] == 17200.00


def test_normalizer_test_detects_missing_detect_function(staging_dir, sample_csv_file):
    normalizer_stage(key="bad_broker", source=BAD_NORMALIZER_NO_DETECT)
    out = normalizer_test(key="bad_broker", file_path=str(sample_csv_file))
    assert out["status"] == "error"
    assert "detect" in out["error"]


def test_normalizer_test_not_staged():
    out = normalizer_test(key="nonexistent", file_path="/tmp/x.csv")
    assert out["status"] == "error"


# ---------------------------------------------------------------------------
# normalizer_activate
# ---------------------------------------------------------------------------

def test_normalizer_activate_moves_to_active(staging_dir, sample_csv_file):
    normalizer_stage(key="test_broker", source=VALID_NORMALIZER_SOURCE)
    normalizer_test(key="test_broker", file_path=str(sample_csv_file))
    out = normalizer_activate(key="test_broker")
    assert out["status"] == "ok"
    active_path = Path(out["active_path"])
    assert active_path.exists()
    # Staging copy should be gone
    staging_path = staging_dir / ".risk_module" / "normalizers" / ".staging" / "test_broker.py"
    assert not staging_path.exists()


def test_normalizer_activate_requires_staged_file(staging_dir):
    out = normalizer_activate(key="nonexistent")
    assert out["status"] == "error"


def test_normalizer_activate_requires_tested_marker(staging_dir):
    """Cannot activate without running normalizer_test first."""
    normalizer_stage(key="untested", source=VALID_NORMALIZER_SOURCE)
    out = normalizer_activate(key="untested")
    assert out["status"] == "error"
    assert "not passed testing" in out["error"]


# ---------------------------------------------------------------------------
# normalizer_test — negative cases
# ---------------------------------------------------------------------------

def test_normalizer_test_fails_on_detect_false(staging_dir, sample_csv_file):
    """detect() returning False is a validation error."""
    source = textwrap.dedent("""\
        from inputs.position_schema import NormalizeResult
        def detect(lines):
            return False
        def normalize(lines, filename):
            return NormalizeResult(positions=[], errors=[], warnings=[], brokerage_name="X")
    """)
    normalizer_stage(key="bad_detect", source=source)
    out = normalizer_test(key="bad_detect", file_path=str(sample_csv_file))
    assert out["status"] == "error"
    assert out["detect_result"] is False
    assert any("detect() returned False" in e for e in out["validation_errors"])


def test_normalizer_test_fails_on_result_errors(staging_dir, sample_csv_file):
    """Normalizer that reports errors in result.errors fails validation."""
    source = textwrap.dedent("""\
        from inputs.position_schema import NormalizeResult
        def detect(lines):
            return True
        def normalize(lines, filename):
            return NormalizeResult(
                positions=[], errors=["Row 1: bad data"], warnings=[], brokerage_name="X"
            )
    """)
    normalizer_stage(key="has_errors", source=source)
    out = normalizer_test(key="has_errors", file_path=str(sample_csv_file))
    assert out["status"] == "error"
    assert any("error(s)" in e for e in out["validation_errors"])


def test_normalizer_test_fails_on_dict_positions(staging_dir, sample_csv_file):
    """Positions must be PositionRecord instances, not dicts."""
    source = textwrap.dedent("""\
        from inputs.position_schema import NormalizeResult
        def detect(lines):
            return True
        def normalize(lines, filename):
            return NormalizeResult(
                positions=[{"ticker": "AAPL", "quantity": 100, "value": 17200}],
                errors=[], warnings=[], brokerage_name="X"
            )
    """)
    normalizer_stage(key="dict_pos", source=source)
    out = normalizer_test(key="dict_pos", file_path=str(sample_csv_file))
    assert out["status"] == "error"
    assert any("PositionRecord" in e for e in out["validation_errors"])


# ---------------------------------------------------------------------------
# End-to-end: stage → test → activate → detect_and_normalize finds it
# ---------------------------------------------------------------------------

def test_e2e_activated_normalizer_discovered_by_detect(staging_dir, sample_csv_file):
    """After activation, detect_and_normalize() finds the new normalizer.

    The staging_dir fixture sets both _DIRS and HOME so the activated file
    lands in ~/.risk_module/normalizers/ (= tmp_path/.risk_module/normalizers/)
    where _load_user_normalizers() will find it.
    """
    from inputs.normalizers import detect_and_normalize

    normalizer_stage(key="test_broker", source=VALID_NORMALIZER_SOURCE)
    normalizer_test(key="test_broker", file_path=str(sample_csv_file))
    normalizer_activate(key="test_broker")

    lines = sample_csv_file.read_text().splitlines()
    result = detect_and_normalize(lines, "sample.csv")
    assert result is not None
    assert result.brokerage_name == "Test Broker"
    assert len(result.positions) == 2


def test_e2e_user_normalizer_discovered_in_db_mode(staging_dir, sample_csv_file, monkeypatch):
    """Regression: user normalizers must be found even when DB is available.

    The web app always has a DB connection. Before the Step 2.0 fix,
    _all_normalizers() skipped user normalizers when is_db_available() was True.
    """
    import database
    from inputs.normalizers import detect_and_normalize

    monkeypatch.setattr(database, "is_db_available", lambda: True)

    normalizer_stage(key="test_broker", source=VALID_NORMALIZER_SOURCE)
    normalizer_test(key="test_broker", file_path=str(sample_csv_file))
    normalizer_activate(key="test_broker")

    lines = sample_csv_file.read_text().splitlines()
    result = detect_and_normalize(lines, "sample.csv")
    assert result is not None
    assert result.brokerage_name == "Test Broker"


# ---------------------------------------------------------------------------
# normalizer_list
# ---------------------------------------------------------------------------

def test_normalizer_list_includes_staged_and_active(staging_dir, sample_csv_file):
    normalizer_stage(key="staged_one", source=VALID_NORMALIZER_SOURCE)
    normalizer_stage(key="active_one", source=VALID_NORMALIZER_SOURCE)
    normalizer_test(key="active_one", file_path=str(sample_csv_file))
    normalizer_activate(key="active_one")
    out = normalizer_list()
    assert out["status"] == "ok"
    assert "staged_one" in out["staged"]
    assert "active_one" in out["active"]
    assert "staged_one" not in out["active"]
```

**Run with**: `pytest tests/mcp_tools/test_normalizer_builder.py -x -q`

**Total tests in this file**: 18 (sample_csv: 2, stage: 3, test_positive: 2, test_negative: 4, activate: 3, list: 1, e2e: 2, not_staged: 1)

---

### Phase 3: Inline Chat Panel + `stage-csv` Endpoint

**Goal**: Wire the "Build with AI" button to an inline chat panel that drives the normalizer builder, then auto-retries import on success.

**Depends on**: Phase 1 + Phase 2 complete.

---

#### Step 3.1 — Add `POST /api/onboarding/stage-csv` endpoint

**File**: `routes/onboarding.py`

Add a module-level constant and a new endpoint **after** the existing `import_onboarding_csv` endpoint:

```python
import uuid as _uuid

_STAGED_CSV_DIR = Path(tempfile.gettempdir()) / "normalizer_builder"


_STAGED_CSV_TTL_SECONDS = 3600  # 1 hour


def _cleanup_stale_staged_csvs() -> None:
    """Remove staged CSVs older than TTL. Best-effort, no exceptions."""
    import time
    if not _STAGED_CSV_DIR.is_dir():
        return
    cutoff = time.time() - _STAGED_CSV_TTL_SECONDS
    for f in _STAGED_CSV_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass


def _stage_csv_for_builder(upload: UploadFile, content: bytes) -> str:
    """Write CSV to a stable temp path for the normalizer builder."""
    _STAGED_CSV_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "upload.csv").suffix or ".csv"
    staged_path = _STAGED_CSV_DIR / f"{_uuid.uuid4().hex}{suffix}"
    staged_path.write_bytes(content)
    return str(staged_path)


@onboarding_router.post("/stage-csv")
async def stage_csv_for_builder(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Stage a CSV for the normalizer builder. Returns a stable file_path.

    Files are written to a temp dir. Cleanup: files older than 1 hour are
    purged on each call (cheap since the dir is small).
    """
    _get_authenticated_user(request)
    content = await file.read()
    await file.close()
    _cleanup_stale_staged_csvs()
    staged_path = _stage_csv_for_builder(file, content)
    return {"file_path": staged_path, "filename": file.filename or "upload.csv"}
```

Add `import uuid as _uuid` at the top of the file (the `Path`, `tempfile` imports already exist). **Do NOT** modify any existing endpoints.

---

#### Step 3.2 — Create `NormalizerBuilderPanel.tsx`

**File**: `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx` **(NEW)**

Props interface:

```typescript
interface NormalizerBuilderPanelProps {
  /** Stable file path returned by POST /api/onboarding/stage-csv */
  filePath: string;
  /** Original filename for display */
  filename: string;
  /** Column names detected by the backend */
  detectedHeaders: string[];
  /** First N lines of the CSV for context */
  sampleLines: string[];
  /** Called when the normalizer is activated and the import should be retried */
  onNormalizerActivated: () => void;
  /** Called when the user dismisses the panel */
  onClose: () => void;
}
```

Implementation requirements:

**GatewayClaudeService instantiation**:
- Constructor: `new GatewayClaudeService({ url: '/api/gateway' })` — this is the same URL used by the main app chat in `usePortfolioChat.ts` line 188. Do NOT use `window.location.origin`.
- Import from: `import { GatewayClaudeService } from '@risk/chassis'`

**ChatMessage type contract** (from `@risk/chassis` types):
```typescript
interface ChatMessage {
  id?: string;
  type: 'user' | 'assistant' | 'error';  // REQUIRED — not optional
  role?: 'user' | 'assistant';            // optional alias
  content: string;
  timestamp?: string;
}
```
Local message state must include the `type` field. Use `type: 'user'` or `type: 'assistant'`.

**`sendMessageStream(message, history)` behavior**:
- The method auto-appends the current `message` to the request. The `history` parameter must contain **only prior messages**, NOT the current message. Passing the current message in both `message` and `history` will duplicate it.
- History format: `ChatMessage[]` with the `type` field set.

**On mount**:
- Send an initial message via `sendMessageStream(initialPrompt, [])` (empty history for first message)
- The `initialPrompt` string contains filename, file path, detected headers, first 6 sample lines, and instructions to use normalizer builder tools

**Streaming**:
- `for await (const chunk of service.sendMessageStream(message, priorHistory))` — accumulate `text_delta` chunks into the current assistant message
- Handle `tool_approval_request` chunks by auto-approving normalizer builder tools (tool names starting with `normalizer_`) via `service.respondToApproval(toolCallId, nonce, true)`, and showing an approval prompt for anything else
- **Activation detection**: When a `tool_result` chunk arrives for `normalizer_activate` with status `"ok"`, call `onNormalizerActivated()` after a short delay (500ms) to let the user see the success message

**UI**:
- Render with tailwind classes matching the existing card/panel style. Use `Card` and `CardContent` from `../ui/card`
- Max height: `max-h-[500px]` with `overflow-y-auto` on the message container
- Show a subtle loading indicator while streaming
- Minimal chat UI: scrollable message list + text input + send button

**Do NOT** import or use `ChatCore`, `ChatContext`, or `useSharedChat` — this is an independent mini-chat.

---

#### Step 3.3 — Wire `NormalizerBuilderPanel` into `CsvImportStep`

**File**: `frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx`

Add state and handler for the builder panel:

```typescript
const [showBuilder, setShowBuilder] = useState(false);
const [stagedFilePath, setStagedFilePath] = useState<string | null>(null);
const [stagedFilename, setStagedFilename] = useState<string>('');
```

Replace the disabled "Build with AI" button (from Phase 1, Step 1.3) with a working version:

```typescript
<Button
  variant="premium"
  size="sm"
  onClick={handleBuildWithAI}
  disabled={isPreviewing || isSubmitting}
>
  Build with AI
</Button>
```

Add the handler:

```typescript
const handleBuildWithAI = async () => {
  if (!selectedFile || !api) return;

  const formData = new FormData();
  formData.append('file', selectedFile);

  try {
    const result = await api.request<{ file_path: string; filename: string }>(
      '/api/onboarding/stage-csv',
      { method: 'POST', body: formData },
    );
    setStagedFilePath(result.file_path);
    setStagedFilename(result.filename);
    setShowBuilder(true);
  } catch (err) {
    setErrorMessage(err instanceof Error ? err.message : 'Failed to stage CSV for builder.');
  }
};
```

Add the auto-retry handler:

```typescript
const handleNormalizerActivated = async () => {
  setShowBuilder(false);
  setStagedFilePath(null);
  setNeedsNormalizerData(null);
  setInstitution('');           // Clear stale institution to prevent forcing wrong normalizer
  setErrorMessage(null);
  if (selectedFile) {
    await requestPreview(selectedFile, '');  // Empty institution = auto-detect with new normalizer
  }
};
```

Render the panel conditionally, below the `needs_normalizer` card:

```tsx
{showBuilder && stagedFilePath && needsNormalizerData ? (
  <NormalizerBuilderPanel
    filePath={stagedFilePath}
    filename={stagedFilename}
    detectedHeaders={needsNormalizerData.detected_headers ?? []}
    sampleLines={needsNormalizerData.first_20_lines ?? []}
    onNormalizerActivated={handleNormalizerActivated}
    onClose={() => setShowBuilder(false)}
  />
) : null}
```

Add the import at the top:
```typescript
import { NormalizerBuilderPanel } from './NormalizerBuilderPanel';
```

---

#### Step 3.4 — Tests

**File**: `tests/routes/test_onboarding_stage_csv.py` **(NEW)**

```python
"""Tests for POST /api/onboarding/stage-csv endpoint."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client with the onboarding router."""
    from app import create_app
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def auth_user(monkeypatch):
    """Mock authenticated user."""
    user = {"user_id": 1, "email": "test@example.com"}
    monkeypatch.setattr(
        "routes.onboarding.auth_service.get_user_by_session",
        lambda _: user,
    )
    return user


@pytest.fixture(autouse=True)
def _isolate_staged_dir(monkeypatch, tmp_path):
    """Redirect staged CSV dir to tmp_path to avoid polluting shared temp."""
    staged = tmp_path / "normalizer_builder"
    staged.mkdir()
    monkeypatch.setattr("routes.onboarding._STAGED_CSV_DIR", staged)
    return staged


def test_stage_csv_returns_stable_path(client, auth_user, _isolate_staged_dir):
    csv_content = b"Symbol,Quantity,Value\nAAPL,100,17200\n"
    response = client.post(
        "/api/onboarding/stage-csv",
        files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        cookies={"session_id": "test-session"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "file_path" in data
    assert data["filename"] == "test.csv"
    assert Path(data["file_path"]).exists()


def test_stage_csv_requires_auth(client):
    csv_content = b"Symbol,Quantity,Value\n"
    response = client.post(
        "/api/onboarding/stage-csv",
        files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert response.status_code == 401


def test_preview_csv_forwards_detected_headers(client, auth_user, monkeypatch):
    """preview-csv endpoint forwards detected_headers from needs_normalizer response."""
    csv_content = b"Symbol,Quantity,Value\nAAPL,100,17200\n"
    # Force needs_normalizer by returning None from detect_and_normalize
    monkeypatch.setattr(
        "mcp_tools.import_portfolio.detect_and_normalize", lambda *a: None
    )
    response = client.post(
        "/api/onboarding/preview-csv",
        files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        cookies={"session_id": "test-session"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "needs_normalizer"
    assert "detected_headers" in data
    assert isinstance(data["detected_headers"], list)
```

**Run with**: `pytest tests/routes/test_onboarding_stage_csv.py -x -q`

Frontend tests: Manual verification or Vitest test that `NormalizerBuilderPanel` renders given props and calls `onNormalizerActivated` when expected.

---

## Phase Sequencing & Dependencies

```
Phase 1 (Steps 1.1–1.5)           ←── standalone, no dependencies
    │                                   Codex task: backend + frontend
    ├── enriched needs_normalizer response
    └── "Build with AI" button (disabled placeholder)

Phase 2 (Steps 2.0–2.3)           ←── standalone, no dependencies
    │                                   Codex task: backend only
    ├── Step 2.0: remove DB gate in _all_normalizers()
    ├── normalizer_builder.py (5 tools)
    ├── mcp_server.py (5 registrations)
    └── test_normalizer_builder.py (18 tests)

Phase 3 (Steps 3.1–3.4)           ←── depends on Phase 1 + Phase 2
    │                                   Codex task: backend + frontend
    ├── stage-csv endpoint
    ├── NormalizerBuilderPanel.tsx
    ├── CsvImportStep.tsx wiring
    └── test_onboarding_stage_csv.py
```

Phases 1 and 2 can be dispatched to Codex in parallel. Phase 3 after both land.

## Estimated Scope

| Phase | New files | Modified files | Tests | Total |
|-------|-----------|----------------|-------|-------|
| Phase 1 | 0 | 4 | 4 | ~4 |
| Phase 2 | 2 | 2 | 18 | ~4 |
| Phase 3 | 2 | 2 | 3 | ~4 |

## Constraints for Codex

- **Do NOT** modify any existing MCP tool implementations, normalizer modules, or test files unless explicitly listed
- **Do NOT** refactor neighboring code, add type annotations to unchanged functions, or add docstrings to unchanged functions
- **DO** modify `inputs/normalizers/__init__.py` `_all_normalizers()` per Step 2.0 — remove the `is_db_available()` gate so user normalizers are always loaded. **Do NOT** change `_load_user_normalizers()` or `_load_module_from_path()`
- **Do NOT** create any new database tables or migrations
- **Do NOT** modify `useOnboardingActivation.ts` logic (type-only change in Step 1.4)
- Frontend changes must compile with zero new TypeScript errors
- Backend changes must pass `pytest tests/inputs/test_normalizers.py tests/mcp_tools/test_import_portfolio.py tests/mcp_tools/test_normalizer_builder.py tests/routes/test_onboarding_stage_csv.py -x -q`

## Open Questions

1. **Transaction normalizer builder** — Phase 2 includes the `normalizer_type="transaction"` parameter but only validates position output. Transaction schema validation is a small follow-up.

2. **Security sandbox** — the finance-cli normalizer builder runs generated code in a restricted sandbox. Phase 2 loads modules with bare `importlib` (same as existing `_load_module_from_path` in `inputs/normalizers/__init__.py`). Sandboxing can be added as a follow-up.

3. **Tool auto-approval** — Phase 3 auto-approves `normalizer_*` tools via `service.respondToApproval(toolCallId, nonce, true)`. All other tools show approval UI. This may need refinement based on gateway approval flow behavior.

## Resolved Issues (from Codex review round 1)

- **DB-mode blocker**: `_all_normalizers()` now always loads user normalizers (Step 2.0)
- **Validation strictness**: `_validate_position_result()` duck-type checks for `to_dict()` and `ticker` (rejects plain dicts), checks `detect_result`, checks `result.errors`
- **Activation gating**: `.tested` marker file required — cannot activate without passing test
- **MCP types**: Wrappers use `Literal["position", "transaction"]` not bare `str`
- **Frontend types**: `header_line_index: number | null`, `ChatMessage.type` field required
- **GatewayClaudeService URL**: `'/api/gateway'` (not `window.location.origin`)
- **History handling**: `sendMessageStream(message, priorHistory)` — prior messages only, current auto-appended
- **State cleanup**: `handleNormalizerActivated` clears `institution`, `showBuilder`, `stagedFilePath`, all error state
- **Stage-csv cleanup**: `await file.close()`, TTL-based cleanup of stale files
- **Test coverage**: 18 tests in Phase 2 (incl. negative cases, e2e, DB-mode regression), 3 route-level tests in Phase 3
- **Stale docs**: Built-in position normalizers = IBKR + Schwab (not IBKR only)

## Resolved Issues (from Codex review round 2)

- **HOME isolation in test**: `test_registry_returns_none_for_unrecognized_csv` now gets `monkeypatch.setenv("HOME", str(tmp_path))` to prevent scanning real HOME after DB gate removal (Step 2.0, item 4)
- **Validation scope**: `_validate_position_result()` now validates ALL positions (`result.positions`), not just first 5 (`result.positions[:5]`)
- **Stale `.tested` marker**: `normalizer_stage()` now clears `{key}.tested` on restage — prevents activating untested code after restage
- **Test `.tested` gate consistency**: `test_normalizer_activate_moves_to_active` and `test_normalizer_list_includes_staged_and_active` now call `normalizer_test()` before `normalizer_activate()` to satisfy the `.tested` marker gate

## Resolved Issues (from Codex review round 3)

- **Stale institution on file change**: `handleFileChange` state cleanup rule now explicitly calls `requestPreview(nextFile, '')` with empty institution after clearing state
- **Malformed `result.positions`**: `normalizer_test()` now guards `positions` access with `getattr(result, "positions", None)` + `isinstance(list)` check — handles `positions=None` or non-list without raising
- **Missing `first_20_lines` in type**: `CsvImportCompletionResponse` now includes `first_20_lines?: string[]` to match the field already forwarded by `_shape_csv_error()`
- **Broken code fence**: Step 3.4 `test_preview_csv_forwards_detected_headers` moved inside the code fence

## Resolved Issues (from Codex review round 4)

- **Test import style**: Step 1.5 tests now use `import_portfolio_tool.import_portfolio(...)` matching the existing test file's `import mcp_tools.import_portfolio as import_portfolio_tool` convention
- **Missing `row_count` in types**: Both `CsvPreviewResponse` and `CsvImportCompletionResponse` now include `row_count?: number` to match `_shape_csv_error()` forwarding
- **DB-mode regression test**: New `test_e2e_user_normalizer_discovered_in_db_mode` forces `is_db_available()=True` and verifies user normalizers are still found (18 tests total)

## Resolved Issues (from Codex review round 5)

- **Phase dependency clarity**: Phase 1 cleanup rules no longer reference Phase 3 state (`showBuilder`, `stagedFilePath`). Phase 3 extensions called out in a blockquote note
- **Sequencing table**: Phase 2 now listed as Steps 2.0–2.3 with explicit Step 2.0 (DB gate removal) entry
- **Validation docstring accuracy**: `_validate_position_result()` docstring now correctly describes duck-typing checks (`hasattr`/`to_dict`) instead of claiming `isinstance(PositionRecord)` enforcement

## Resolved Issues (from Codex review round 6)

- **Stale NormalizeResult snippet**: Q4 snippet now matches current `position_schema.py` (includes `skipped_rows`, `base_currency`, correct field order)
- **Key files table**: Fixed `ibkr.py` row — now lists both `ibkr.py` and `schwab.py` as built-in position normalizers
- **Reference flow signatures**: `normalizer_sample_csv(file_path)` and `normalizer_test(key, file_path)` now match actual definitions
- **Test counts**: Phase 2 = 18 tests, Phase 3 = 3 tests (corrected throughout spec)
