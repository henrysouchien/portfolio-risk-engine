# E2E Test Plan: Onboarding + AI Normalizer Builder

## Context

The onboarding flow (OnboardingWizard / EmptyPortfolioLanding → CsvImportStep → NormalizerBuilderPanel → ProcessingStep → CompletionStep) has zero E2E test coverage. The AI normalizer builder — where Claude iterates through `normalizer_sample_csv` → `normalizer_stage` → `normalizer_test` → `normalizer_activate` via Gateway SSE — is the most complex path and highest-risk for regressions. This plan adds Playwright E2E tests covering both the happy-path CSV import and the full AI normalizer flow with a deterministic gateway mock.

**All tests are fully mocked** — no live backend required. Every API endpoint is intercepted via `page.route()` for deterministic, isolated execution.

**Cross-origin handling**: The app's `HttpClient` (`app-platform/src/http/HttpClient.ts:36`) prefixes `VITE_API_URL` to endpoints. The default value is `http://localhost:5001`, making API calls cross-origin from the page on `:3000`. The HTTP client sends `credentials: 'include'` and `X-Requested-With` headers (`HttpClient.ts:144,177`), triggering CORS preflights for cross-origin requests.

**Solution**: Create `frontend/.env.e2e` with `VITE_API_URL=http://localhost:3000`. This is a valid URL (passes Zod `z.string().url()` validation) and makes all `HttpClient` requests same-origin — the browser sends them to `:3000`, where the Vite dev proxy forwards `/api`, `/auth`, `/plaid` to `:5001`. Playwright's `page.route('**/api/**')` intercepts these same-origin requests before they reach the Vite proxy. No CORS headers or `OPTIONS` handling needed.

Start the frontend dev server for E2E with: `cd frontend && npx vite --mode e2e`

The `GatewayClaudeService` already uses relative paths (`/api/gateway/chat` at `GatewayClaudeService.ts:117`), so it is unaffected by this change.

---

## Architecture: How the Gateway Mock Works

The `NormalizerBuilderPanel` creates a `GatewayClaudeService({ url: '/api/gateway' })` which does:
- `POST /api/gateway/chat` → reads response body as SSE via `parseSSE(response.body)`
- `POST /api/gateway/tool-approval` → sends approval decisions

The SSE parser (`GatewayClaudeService.ts:40-78`) reads `data: {json}\n\n` chunks and `mapEvent()` translates:
- `{ type: "text_delta", text: "..." }` → `text_delta`
- `{ type: "tool_call_start", tool_name: "..." }` → `tool_call_start`
- `{ type: "tool_approval_request", tool_call_id, nonce, tool_name, tool_input }` → mapped by `mapEvent()`, then auto-approved in `NormalizerBuilderPanel.tsx:179` if tool name starts with `normalizer_`
- `{ type: "tool_call_complete", tool_call_id, tool_name, result }` → `tool_result`
- `data: [DONE]` → `done`

**Strategy**: Use `page.route('**/api/gateway/chat')` to return a static SSE body containing the full tool-call sequence. Also intercept `**/api/gateway/tool-approval` → 200 OK. The frontend's async SSE reader consumes events sequentially from the pre-buffered response. The `respondToApproval()` `await` inside the `for await` loop fires asynchronously and completes against the mocked approval endpoint, then the loop continues reading the next buffered event. This is confirmed compatible with `parseSSE()`'s boundary logic.

**Note on timing**: The static `route.fulfill()` body is delivered synchronously by Playwright, not as a live chunked stream. This is sufficient for testing the UI state machine and event handling, but does not validate real-world streaming latency. Assertions should target stable end-states (e.g., final message content, panel visibility), not transient intermediate states (e.g., individual status text updates during streaming).

---

## Onboarding Surface Selection

`ModernDashboardApp.tsx:123-151` renders `OnboardingBootstrapSurface` which checks:
- If neither `onboarding_completed_{userId}` nor `onboarding_dismissed_{userId}` is `'true'` → shows `OnboardingWizard`
- If either key's value is exactly `'true'` → shows `EmptyPortfolioLanding`

The empty portfolio path is triggered when the `GET /api/v2/portfolios` response has `{ portfolios: [] }`. `usePortfolioList()` (query key `['portfolios', 'v2', 'list']`) returns a sorted array from `response.portfolios`, and when that array is empty, `PortfolioInitializer.tsx:159` throws `createEmptyPortfolioError()`.

**Test approach**:
- **Suite 1 (CSV happy path) and Suite 2 (normalizer builder)**: Set `onboarding_dismissed_{userId}` to `'true'` in localStorage so `EmptyPortfolioLanding` renders directly (the app checks `=== 'true'`, not just key presence — see `ModernDashboardApp.tsx:130-132`).
- **Suite 4 (wizard navigation)**: Ensure both `onboarding_completed_{userId}` and `onboarding_dismissed_{userId}` are absent (or not `'true'`) so `OnboardingWizard` renders. Add `data-testid` to wizard-specific elements.

---

## File Structure

```
e2e/
├── playwright.config.ts              # Config (baseURL :3000, frontend webServer only)
├── global-setup.ts                   # Inject auth state → e2e/auth-state.json
├── fixtures/
│   ├── schwab-positions.csv          # Recognized Schwab format (matches real normalizer)
│   ├── unknown-broker.csv            # Triggers needs_normalizer
│   ├── invalid.csv                   # Malformed
│   └── empty.csv                     # 0 bytes
├── helpers/
│   ├── gateway-mock.ts               # SSE event builder + route handlers
│   ├── onboarding-page.ts            # Page Object Model
│   └── api-mocks.ts                  # Common API route interceptors
├── tests/
│   ├── csv-import-happy-path.spec.ts # Suite 1: recognized CSV flow
│   ├── normalizer-builder.spec.ts    # Suite 2: AI normalizer flow
│   ├── csv-import-errors.spec.ts     # Suite 3: error cases
│   └── onboarding-navigation.spec.ts # Suite 4: wizard navigation + edge paths
```

---

## Step 1: Add `data-testid` Attributes

Surgical additions only — one prop per element, no logic changes.

### `CsvImportStep.tsx`
| Element | `data-testid` |
|---------|---------------|
| `<Input id="csv-file">` (line 228) | `csv-file-input` |
| `<Input id="csv-institution">` (line 254) | `csv-institution-input` |
| "Can't auto-detect?" button (line 237) | `csv-select-institution` |
| "Previewing..." text (line 270) | `csv-previewing` |
| Error card (line 275) | `csv-error-message` |
| needs_normalizer card (line 283) | `csv-needs-normalizer` |
| "Auto-detect with AI" button (line 331) | `csv-build-with-ai` |
| Preview card (success) (line 355) | `csv-preview-card` |
| Cancel button (line 405) | `csv-cancel` |
| "Confirm import" button (line 408) | `csv-confirm-import` |
| Dialog "Import CSV" button (line 443) | `csv-confirm-dialog-import` |

### `NormalizerBuilderPanel.tsx`
| Element | `data-testid` |
|---------|---------------|
| Root Card (line 283) | `normalizer-builder-panel` |
| Close button (line 292) | `normalizer-builder-close` |
| Message viewport div (line 297) | `normalizer-builder-messages` |
| Status text streaming indicator (line 353) | `normalizer-builder-status` |
| Textarea (line 363) | `normalizer-builder-input` |
| Send button (line 375) | `normalizer-builder-send` |

### `EmptyPortfolioLanding.tsx`
| Element | `data-testid` |
|---------|---------------|
| "Connect a brokerage" button (line 140) | `landing-connect-brokerage` |
| "Import a CSV" button (line 143) | `landing-import-csv` |

### `CompletionStep.tsx`
| Element | `data-testid` |
|---------|---------------|
| Root div (line 50) | `completion-step` |
| StatPair "Positions loaded" (line 69) | `completion-positions-count` |
| StatPair "Portfolio value" (line 70) | `completion-portfolio-value` |
| "Go to Dashboard" button (line 77) | `completion-go-to-dashboard` |
| "Connect another" button (line 83) | `completion-connect-another` |
| "Try again" button (line 89) | `completion-retry` |
| "Skip for now" button (line 94) | `completion-skip` |

### `ProcessingStep.tsx`
| Element | `data-testid` |
|---------|---------------|
| Root div (line 25) | `processing-step` |

### `OnboardingWizard.tsx` (for Suite 4)
| Element | `data-testid` |
|---------|---------------|
| Root Dialog/container | `onboarding-wizard` |
| Progress bar | `onboarding-wizard-progress` |

**Files**: `CsvImportStep.tsx`, `NormalizerBuilderPanel.tsx`, `EmptyPortfolioLanding.tsx`, `CompletionStep.tsx`, `ProcessingStep.tsx`, `OnboardingWizard.tsx`

---

## Step 2: Playwright Config + Global Setup

### `e2e/playwright.config.ts`
- `baseURL: 'http://localhost:3000'`
- `timeout: 90_000` (normalizer builder flow is multi-step)
- `use.storageState: 'e2e/auth-state.json'`
- `retries: 1` local, `2` in CI
- `workers: 1` (sequential — tests share mocked state patterns)
- `webServer`: frontend (:3000) only, started with `--mode e2e` (uses `.env.e2e`), with `reuseExistingServer: true`. No backend webServer needed — all API calls are intercepted via `page.route()`
- `reporter: [['html'], ['list']]`
- Single project: `chromium` only

### `e2e/global-setup.ts`
Create `auth-state.json` with:
- Cookie: `session_id=e2e-test-session` on `localhost`
- No localStorage auth entries needed — auth state is initialized at runtime by `authStore.checkAuthStatus()` calling `GET /auth/status`, which is intercepted by `mockAuth()`
- localStorage onboarding keys are set per-suite in `beforeEach` hooks (not global setup)

### `e2e/tsconfig.json`
Extend from root or standalone config with `@playwright/test` types.

### `.gitignore` additions
```
e2e/auth-state.json
playwright-report/
```

### `frontend/package.json`
Add missing script:
```json
"test:e2e": "npx playwright test --config ../e2e/playwright.config.ts"
```

---

## Step 3: Fixture CSV Files

### `schwab-positions.csv` — Recognized by built-in Schwab normalizer

Must match `_REQUIRED_COLUMNS` from `inputs/normalizers/schwab.py:15`: `Symbol`, `Description`, `Qty (Quantity)`, `Price`, `Mkt Val (Market Value)`, `Cost Basis`, `Asset Type`.

```csv
"Positions for account Brokerage XXXX-1234 as of 03/16/2026"
""
"Symbol","Description","Qty (Quantity)","Price","Mkt Val (Market Value)","Cost Basis","Asset Type"
"AAPL","APPLE INC","50","$172.00","$8,600.00","$7,500.00","Equity"
"MSFT","MICROSOFT CORP","30","$415.00","$12,450.00","$10,200.00","Equity"
"VTI","VANGUARD TOTAL STOCK MKT ETF","100","$265.00","$26,500.00","$22,000.00","ETFs & Closed End Funds"
"Cash & Cash Investments","--","--","--","$5,450.00","--","Cash and Money Market"
"Account Total","","","","$53,000.00","$39,700.00",""
```

### `unknown-broker.csv` — No built-in normalizer matches
```csv
Instrument,Units,Avg Cost,Current Price,Market Value,Unrealized P&L,Currency
AAPL US Equity,50,150.00,172.00,8600.00,1100.00,USD
MSFT US Equity,30,340.00,415.00,12450.00,2250.00,USD
VTI US Equity,100,220.00,265.00,26500.00,4500.00,USD
```

### `invalid.csv`
```
This is not a valid CSV file
It has no structure whatsoever
random text lines
```

### `empty.csv` — 0 bytes

---

## Step 4: Gateway Mock Helper (`e2e/helpers/gateway-mock.ts`)

```typescript
import type { Page, Route } from '@playwright/test';

// Core: format a single SSE event
export function formatSSE(event: Record<string, unknown>): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

// Build complete normalizer builder SSE stream
export function buildNormalizerBuilderStream(): string {
  return [
    // Claude thinks...
    formatSSE({ type: "text_delta", text: "I'll analyze your CSV and build a normalizer. " }),
    formatSSE({ type: "text_delta", text: "Let me start by reading the file.\n\n" }),

    // Tool 1: normalizer_sample_csv
    formatSSE({ type: "tool_call_start", tool_name: "normalizer_sample_csv" }),
    formatSSE({ type: "tool_approval_request", tool_call_id: "tc_1", nonce: "n_1",
                tool_name: "normalizer_sample_csv", tool_input: { file_path: "/tmp/staged.csv", lines: 20 } }),
    formatSSE({ type: "tool_call_complete", tool_call_id: "tc_1", tool_name: "normalizer_sample_csv",
                result: { status: "ok", lines: ["Instrument,Units,..."], total_lines: 4 } }),

    // Claude plans the normalizer...
    formatSSE({ type: "text_delta", text: "I can see the columns. Let me write the normalizer.\n\n" }),

    // Tool 2: normalizer_stage
    formatSSE({ type: "tool_call_start", tool_name: "normalizer_stage" }),
    formatSSE({ type: "tool_approval_request", tool_call_id: "tc_2", nonce: "n_2",
                tool_name: "normalizer_stage", tool_input: { key: "e2e_unknown_broker", source: "..." } }),
    formatSSE({ type: "tool_call_complete", tool_call_id: "tc_2", tool_name: "normalizer_stage",
                result: { status: "ok", key: "e2e_unknown_broker" } }),

    // Tool 3: normalizer_test
    formatSSE({ type: "tool_call_start", tool_name: "normalizer_test" }),
    formatSSE({ type: "tool_approval_request", tool_call_id: "tc_3", nonce: "n_3",
                tool_name: "normalizer_test", tool_input: { key: "e2e_unknown_broker", file_path: "/tmp/staged.csv" } }),
    formatSSE({ type: "tool_call_complete", tool_call_id: "tc_3", tool_name: "normalizer_test",
                result: { status: "ok", positions_count: 3, detect_result: true } }),

    // Tool 4: normalizer_activate
    formatSSE({ type: "tool_call_start", tool_name: "normalizer_activate" }),
    formatSSE({ type: "tool_approval_request", tool_call_id: "tc_4", nonce: "n_4",
                tool_name: "normalizer_activate", tool_input: { key: "e2e_unknown_broker" } }),
    formatSSE({ type: "tool_call_complete", tool_call_id: "tc_4", tool_name: "normalizer_activate",
                result: { status: "ok", key: "e2e_unknown_broker" } }),

    // Claude wraps up
    formatSSE({ type: "text_delta", text: "The normalizer is now active! Your CSV should import correctly." }),
    "data: [DONE]\n\n",
  ].join("");
}

// Build an error SSE stream
export function buildErrorStream(errorMessage: string): string {
  return [
    formatSSE({ type: "error", error: errorMessage }),
    "data: [DONE]\n\n",
  ].join("");
}

// Route handlers
export async function mockGateway(page: Page, stream?: string) {
  await page.route('**/api/gateway/chat', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: stream ?? buildNormalizerBuilderStream(),
    })
  );
  await page.route('**/api/gateway/tool-approval', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
  );
}
```

---

## Step 5: API Mocks (`e2e/helpers/api-mocks.ts`)

Common interceptors used across test suites. **All tests are fully mocked.**

```typescript
import type { Page, Route } from '@playwright/test';

const E2E_USER_ID = 'e2e-test-user';
const E2E_USER_EMAIL = 'e2e@test.com';

// Mock auth: GET /auth/status (used by authStore.checkAuthStatus → AuthService.checkAuthStatus)
export async function mockAuth(page: Page) {
  await page.route('**/auth/status', (route: Route) =>
    route.fulfill({ status: 200, json: {
      authenticated: true,
      user: { id: E2E_USER_ID, email: E2E_USER_EMAIL, name: "E2E Test User" },
    }})
  );
}

// Mock empty portfolio list (triggers onboarding via PortfolioInitializer)
// usePortfolioList() calls GET /api/v2/portfolios → expects { portfolios: [] }
export async function mockEmptyPortfolioList(page: Page) {
  await page.route('**/api/v2/portfolios', (route: Route) =>
    route.fulfill({ status: 200, json: { portfolios: [] } })
  );
}

// Mock preview-csv returning success
// Schwab normalizer produces 4 positions: 3 equities + 1 cash (CUR:USD from "Cash & Cash Investments")
export async function mockPreviewSuccess(page: Page) {
  await page.route('**/api/onboarding/preview-csv', (route: Route) =>
    route.fulfill({ status: 200, json: {
      status: "success",
      positions_count: 4,
      total_value: 53000,
      sample_holdings: [
        { ticker: "AAPL", shares: 50, value: 8600 },
        { ticker: "MSFT", shares: 30, value: 12450 },
        { ticker: "VTI", shares: 100, value: 26500 },
        { ticker: "CUR:USD", shares: 5450, value: 5450 },
      ],
      source_key: "charles_schwab",
    }})
  );
}

// Mock preview-csv returning needs_normalizer
export async function mockPreviewNeedsNormalizer(page: Page) {
  await page.route('**/api/onboarding/preview-csv', (route: Route) =>
    route.fulfill({ status: 200, json: {
      status: "needs_normalizer",
      detected_headers: ["Instrument", "Units", "Avg Cost", "Current Price", "Market Value", "Unrealized P&L", "Currency"],
      first_20_lines: [
        "Instrument,Units,Avg Cost,Current Price,Market Value,Unrealized P&L,Currency",
        "AAPL US Equity,50,150.00,172.00,8600.00,1100.00,USD",
        "MSFT US Equity,30,340.00,415.00,12450.00,2250.00,USD",
        "VTI US Equity,100,220.00,265.00,26500.00,4500.00,USD",
      ],
      row_count: 4,
      header_line_index: 0,
    }})
  );
}

// Mock preview-csv: first call → needs_normalizer, subsequent calls → success
export async function mockPreviewNormalizerThenSuccess(page: Page) {
  let callCount = 0;
  await page.route('**/api/onboarding/preview-csv', (route: Route) => {
    callCount++;
    if (callCount === 1) {
      return route.fulfill({ status: 200, json: {
        status: "needs_normalizer",
        detected_headers: ["Instrument", "Units", "Avg Cost", "Current Price", "Market Value", "Unrealized P&L", "Currency"],
        first_20_lines: [
          "Instrument,Units,Avg Cost,Current Price,Market Value,Unrealized P&L,Currency",
          "AAPL US Equity,50,150.00,172.00,8600.00,1100.00,USD",
          "MSFT US Equity,30,340.00,415.00,12450.00,2250.00,USD",
          "VTI US Equity,100,220.00,265.00,26500.00,4500.00,USD",
        ],
        row_count: 4,
        header_line_index: 0,
      }});
    }
    return route.fulfill({ status: 200, json: {
      status: "success",
      positions_count: 3,
      total_value: 47550,
      sample_holdings: [
        { ticker: "AAPL", shares: 50, value: 8600 },
        { ticker: "MSFT", shares: 30, value: 12450 },
        { ticker: "VTI", shares: 100, value: 26500 },
      ],
      source_key: "e2e_unknown_broker",
    }});
  });
}

// Mock stage-csv
export async function mockStageCsv(page: Page) {
  await page.route('**/api/onboarding/stage-csv', (route: Route) =>
    route.fulfill({ status: 200, json: {
      file_path: "/tmp/normalizer_builder/unknown-broker.csv",
      filename: "unknown-broker.csv",
    }})
  );
}

// Mock import-csv returning success
// Real backend response shape (routes/onboarding.py:305-317):
//   { status, positions_count, warnings, portfolio_data: { holdings, total_portfolio_value, ... }, portfolio_name, source_key }
// Frontend (useOnboardingActivation.ts:213-216) checks:
//   result.status === 'success' && result.portfolio_data && result.portfolio_data.holdings?.length
export async function mockImportSuccess(page: Page) {
  await page.route('**/api/onboarding/import-csv', (route: Route) =>
    route.fulfill({ status: 200, json: {
      status: "success",
      positions_count: 4,
      warnings: [],
      portfolio_data: {
        holdings: [
          { ticker: "VTI", shares: 100, market_value: 26500, security_name: "VANGUARD TOTAL STOCK MKT ETF" },
          { ticker: "MSFT", shares: 30, market_value: 12450, security_name: "MICROSOFT CORP" },
          { ticker: "AAPL", shares: 50, market_value: 8600, security_name: "APPLE INC" },
          { ticker: "CUR:USD", shares: 5450, market_value: 5450, security_name: "USD Cash" },
        ],
        total_portfolio_value: 53000,
        statement_date: "2026-03-16",
        account_type: "CSV Imported Account",
      },
      portfolio_name: "CURRENT_PORTFOLIO",
      source_key: "charles_schwab",
    }})
  );
}

// Mock import-csv returning error
export async function mockImportError(page: Page, message = "Import failed") {
  await page.route('**/api/onboarding/import-csv', (route: Route) =>
    route.fulfill({ status: 200, json: {
      status: "error",
      message,
      positions_count: 0,
      warnings: [],
    }})
  );
}

// Catch-all: abort unmocked API calls to prevent leaking to real backend.
// IMPORTANT: Register this FIRST — Playwright matches routes in LIFO (newest-first)
// order, so specific mocks registered AFTER this will take priority over the catch-all.
// Covers /api/**, /auth/**, and /plaid/** (all proxied paths in vite.config.ts).
export async function mockCatchAllApi(page: Page) {
  for (const pattern of ['**/api/**', '**/auth/**', '**/plaid/**']) {
    await page.route(pattern, (route: Route) => {
      console.warn(`[E2E] Unmocked call aborted: ${route.request().method()} ${route.request().url()}`);
      return route.abort('connectionrefused');
    });
  }
}
```

---

## Step 6: Page Object Model (`e2e/helpers/onboarding-page.ts`)

Encapsulates locator lookups and common interactions:

```typescript
import type { Page } from '@playwright/test';

export class OnboardingPage {
  constructor(private page: Page) {}

  // Landing (EmptyPortfolioLanding)
  get importCsvButton() { return this.page.getByTestId('landing-import-csv'); }
  get connectBrokerageButton() { return this.page.getByTestId('landing-connect-brokerage'); }

  // Wizard (OnboardingWizard)
  get wizard() { return this.page.getByTestId('onboarding-wizard'); }

  // CSV Import
  get fileInput() { return this.page.getByTestId('csv-file-input'); }
  get previewCard() { return this.page.getByTestId('csv-preview-card'); }
  get needsNormalizerCard() { return this.page.getByTestId('csv-needs-normalizer'); }
  get buildWithAiButton() { return this.page.getByTestId('csv-build-with-ai'); }
  get selectInstitutionButton() { return this.page.getByTestId('csv-select-institution'); }
  get institutionInput() { return this.page.getByTestId('csv-institution-input'); }
  get confirmImportButton() { return this.page.getByTestId('csv-confirm-import'); }
  get confirmDialogImport() { return this.page.getByTestId('csv-confirm-dialog-import'); }
  get errorMessage() { return this.page.getByTestId('csv-error-message'); }
  get cancelButton() { return this.page.getByTestId('csv-cancel'); }

  // Normalizer Builder
  get builderPanel() { return this.page.getByTestId('normalizer-builder-panel'); }
  get builderMessages() { return this.page.getByTestId('normalizer-builder-messages'); }
  get builderStatus() { return this.page.getByTestId('normalizer-builder-status'); }
  get builderCloseButton() { return this.page.getByTestId('normalizer-builder-close'); }

  // Completion
  get completionStep() { return this.page.getByTestId('completion-step'); }
  get goToDashboardButton() { return this.page.getByTestId('completion-go-to-dashboard'); }
  get retryButton() { return this.page.getByTestId('completion-retry'); }
  get skipButton() { return this.page.getByTestId('completion-skip'); }

  // Processing
  get processingStep() { return this.page.getByTestId('processing-step'); }

  // Actions
  async uploadCsv(fixturePath: string) {
    await this.fileInput.setInputFiles(fixturePath);
  }

  async confirmImport() {
    await this.confirmImportButton.click();
    await this.confirmDialogImport.click();
  }
}
```

---

## Step 7: Test Suite 1 — CSV Import Happy Path

**File**: `e2e/tests/csv-import-happy-path.spec.ts`

**Approach**: Fully mocked. Auth via `mockAuth()`, empty portfolio via `mockEmptyPortfolioList()`, preview via `mockPreviewSuccess()`, import via `mockImportSuccess()`. Set `onboarding_dismissed_{E2E_USER_ID}=true` in localStorage so `EmptyPortfolioLanding` renders.

### Tests

1. **"Upload CSV → preview shows holdings"**
   - Navigate to app → EmptyPortfolioLanding appears
   - Click `landing-import-csv` → CsvImportStep appears
   - Upload `schwab-positions.csv` → wait for `csv-preview-card` visible
   - Assert: positions count text, sample holdings table rows
   - Assert: `csv-confirm-import` button enabled

2. **"Confirm import → processing → completion success"**
   - Upload + preview as above
   - Click `csv-confirm-import` → confirm dialog → click `csv-confirm-dialog-import`
   - Assert: `completion-step` visible
   - Assert: "Go to Dashboard" button visible

3. **"Cancel returns to idle"**
   - Click `landing-import-csv` → CsvImportStep
   - Click `csv-cancel`
   - Assert: CsvImportStep hidden, landing idle state restored

---

## Step 8: Test Suite 2 — Normalizer Builder Flow (AI)

**File**: `e2e/tests/normalizer-builder.spec.ts`

**Approach**: Fully mocked. Auth, empty portfolio, gateway SSE, tool-approval, stage-csv, and the second preview-csv call all intercepted. Set `onboarding_dismissed_{E2E_USER_ID}=true` for `EmptyPortfolioLanding`.

### Tests

1. **"Unknown CSV triggers needs_normalizer card"**
   - Mock preview-csv → `needs_normalizer`
   - Upload `unknown-broker.csv`
   - Assert: `csv-needs-normalizer` card visible
   - Assert: detected headers displayed as badges
   - Assert: `csv-build-with-ai` button visible

2. **"Build with AI stages CSV and opens builder panel"**
   - Mock stage-csv → `{ file_path, filename }`
   - Click `csv-build-with-ai`
   - Assert: `normalizer-builder-panel` visible

3. **"Full normalizer builder flow → re-preview → import → completion"** (the big one)
   - Setup: `mockPreviewNormalizerThenSuccess()` (first call → needs_normalizer, second → success)
   - Setup: `mockStageCsv()`, `mockGateway()`, `mockImportSuccess()`
   - Flow:
     1. Upload unknown CSV → needs_normalizer card
     2. Click "Auto-detect with AI" → builder panel opens
     3. Builder auto-sends initial prompt → gateway SSE streams all events
     4. Wait for `normalizer-builder-messages` to contain text "normalizer is now active"
     5. `onNormalizerActivated` fires after 500ms → builder hides, re-preview triggers
     6. `csv-preview-card` appears with holdings
     7. Click confirm → completion
   - Assert: `completion-step` visible

4. **"Builder close button hides panel without side effects"**
   - Open builder panel as above
   - Click `normalizer-builder-close`
   - Assert: `normalizer-builder-panel` hidden
   - Assert: `csv-needs-normalizer` card still visible

5. **"Manual institution override re-triggers preview"**
   - Upload unknown CSV → needs_normalizer card
   - Click `csv-select-institution` to show institution input
   - Type "Charles Schwab" into `csv-institution-input`
   - Assert: preview re-triggers (mock returns success on institution-specified call)

---

## Step 9: Test Suite 3 — Error Cases

**File**: `e2e/tests/csv-import-errors.spec.ts`

1. **"Empty file shows error"**
   - Mock preview-csv → `{ status: "error", message: "File is empty" }`
   - Upload `empty.csv`
   - Assert: `csv-error-message` visible

2. **"Invalid CSV shows error"**
   - Mock preview-csv → `{ status: "error", message: "No recognizable columns" }`
   - Upload `invalid.csv`
   - Assert: `csv-error-message` visible

3. **"Network error during preview"**
   - Mock preview-csv → 500
   - Upload any CSV
   - Assert: `csv-error-message` visible

4. **"Gateway SSE error in builder shows error message"**
   - Mock gateway SSE → `buildErrorStream("Gateway timeout")`
   - Open normalizer builder
   - Assert: error message in builder messages area

5. **"stage-csv failure shows error"**
   - Mock preview-csv → needs_normalizer, mock stage-csv → 500
   - Click "Auto-detect with AI"
   - Assert: `csv-error-message` visible (CsvImportStep catches stage failure)

6. **"Import error → completion error → retry"**
   - Mock preview-csv → success, mock import-csv → error
   - Upload CSV → preview → confirm import
   - Assert: `completion-step` visible with error variant
   - Assert: `completion-retry` button visible
   - Click retry
   - Assert: flow restarts (CsvImportStep or processing reappears)

7. **"Tool approval POST failure during builder shows chat error"**
   - Mock gateway chat → SSE with `tool_approval_request` event for `normalizer_sample_csv`
   - Mock gateway tool-approval → 500 (POST fails)
   - The auto-approve call at `NormalizerBuilderPanel.tsx:181` (`await service.respondToApproval(...)`) throws because `GatewayClaudeService.ts:174` throws on non-OK response
   - This propagates to the outer catch at `NormalizerBuilderPanel.tsx:220`, which appends a chat error message
   - Assert: error message visible in `normalizer-builder-messages` (type `'error'` chat bubble, not `approvalError` UI which is only for the manual-approval branch)

---

## Step 10: Test Suite 4 — Wizard Navigation

**File**: `e2e/tests/onboarding-navigation.spec.ts`

**Approach**: Clear both `onboarding_completed` and `onboarding_dismissed` so `OnboardingWizard` renders.

1. **"First-run user sees OnboardingWizard"**
   - Clear localStorage keys → navigate
   - Assert: `onboarding-wizard` visible

2. **"Wizard dismiss hides wizard, shows landing"**
   - Click dismiss/skip on wizard
   - Assert: `onboarding-wizard` hidden
   - Assert: `EmptyPortfolioLanding` visible (with `landing-import-csv` button)

3. **"Skip for now sets dismissed flag"**
   - Reach CompletionStep with a non-success variant (e.g., mock import-csv → error so variant="error")
   - Assert: `completion-skip` button visible (only shown when variant is not "success")
   - Click "Skip for now"
   - Assert: `onboarding_dismissed_{userId}` is `'true'` in localStorage

---

## Implementation Sequence

| # | Step | Files | Depends On |
|---|------|-------|------------|
| 1 | Add `data-testid` attributes | 6 frontend components | — |
| 2 | Create `e2e/` dir + config + tsconfig + .gitignore | `playwright.config.ts`, `global-setup.ts`, `tsconfig.json` | — |
| 3 | Create fixture CSV files | 4 files in `e2e/fixtures/` | — |
| 4 | Build gateway mock helper | `e2e/helpers/gateway-mock.ts` | — |
| 5 | Build API mocks + page object | `e2e/helpers/api-mocks.ts`, `onboarding-page.ts` | Step 1 (testids) |
| 6 | CSV import happy path tests | `csv-import-happy-path.spec.ts` | Steps 1-5 |
| 7 | Normalizer builder tests | `normalizer-builder.spec.ts` | Steps 1-5 |
| 8 | Error case tests | `csv-import-errors.spec.ts` | Steps 1-5 |
| 9 | Wizard navigation tests | `onboarding-navigation.spec.ts` | Steps 1-5 |

Steps 1-4 are independent and can be done in parallel. Steps 6-9 are independent of each other.

---

## Verification

1. **Run existing frontend tests**: `cd frontend && npx vitest run` — ensure `data-testid` additions cause no regressions
2. **Run E2E tests**: `npx playwright test --config e2e/playwright.config.ts`
3. **Fully-mocked mode**: All tests use `page.route()` interceptors — no live backend required
4. **Visual check**: Run with `--headed` to watch the normalizer builder SSE stream play through

---

## Key Files to Modify

- `frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx` — add 11 `data-testid` attrs
- `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx` — add 6 `data-testid` attrs
- `frontend/packages/ui/src/components/onboarding/EmptyPortfolioLanding.tsx` — add 2 `data-testid` attrs
- `frontend/packages/ui/src/components/onboarding/CompletionStep.tsx` — add 7 `data-testid` attrs
- `frontend/packages/ui/src/components/onboarding/ProcessingStep.tsx` — add 1 `data-testid` attr
- `frontend/packages/ui/src/components/onboarding/OnboardingWizard.tsx` — add 2 `data-testid` attrs
- `.gitignore` — add `e2e/auth-state.json`, `playwright-report/`
- `frontend/package.json` — add `test:e2e` script

## New Files to Create

- `e2e/playwright.config.ts`
- `e2e/global-setup.ts`
- `e2e/tsconfig.json`
- `e2e/fixtures/schwab-positions.csv`
- `e2e/fixtures/unknown-broker.csv`
- `e2e/fixtures/invalid.csv`
- `e2e/fixtures/empty.csv`
- `e2e/helpers/gateway-mock.ts`
- `e2e/helpers/api-mocks.ts`
- `e2e/helpers/onboarding-page.ts`
- `e2e/tests/csv-import-happy-path.spec.ts`
- `e2e/tests/normalizer-builder.spec.ts`
- `e2e/tests/csv-import-errors.spec.ts`
- `e2e/tests/onboarding-navigation.spec.ts`
- `frontend/.env.e2e` (contains `VITE_API_URL=http://localhost:3000`)
