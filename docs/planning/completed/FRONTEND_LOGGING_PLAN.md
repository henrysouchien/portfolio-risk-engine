# Frontend Logging Overhaul Plan (v2.1) — IMPLEMENTED

> **Status:** Complete (2026-02-24). All 13 items implemented by Codex. Dead code archived (ArchitecturalLogger, architectural context methods, config flag). Backend fields cleaned up. 1227 tests passing, TypeScript clean.

## Problem Statement

The frontend logging system (`frontendLogger.ts`) has good structural foundations — structured JSON, 7 categories, session tracking, backend piping — but the actual log output is borderline unusable. A single day of usage produces 7,602 lines / 4.2MB, with a terrible signal-to-noise ratio. The logs are difficult for both humans and AI agents to parse for debugging.

**Key evidence from `logs/frontend.jsonl`:**
- ~43% of lines are `EventBus` / `UnifiedAdapterCache` "Data transformation successful" spam with numeric array indices as data (~3,300 lines)
- Identical "Component mounted" logs fire 3-6x per render cycle within the same millisecond
- Cache warming emits ~20 lines every 60 seconds even when all cache hits (no work done)
- Full Google JWT tokens logged in plaintext (security issue — active leak)
- `userAgent` string (~400 bytes) repeated on every line
- `component: "Unknown"` on all network logs
- `url` field shows origin not route path

**Backend ingestion context:** The backend route `routes/frontend_logging.py` (`process_individual_log()`) overwrites two fields from HTTP headers before writing to `frontend.jsonl`:
- `url` ← `request.headers.get('referer', '')` (line 391) — ignores frontend payload
- `userAgent` ← `request.headers.get('user-agent', '')` (line 420) — ignores frontend payload
- `architecturalContext` / `aiAnalysisHint` are **not** written to `structured_event` (line 413-424) — already stripped

This means frontend-only changes to these fields won't affect stored logs. Items that touch these fields must also update the backend route.

## Goals

1. Reduce log volume by ~60-70% without losing meaningful signal
2. Make logs immediately useful for AI/agent debugging ("what happened, what failed, what did the user do?")
3. Fix the security gap (auth token logging in both console and stored logs)
4. Keep the existing `frontendLogger` API surface — no breaking changes to the 82 importing files

## Non-Goals

- Rewriting the logger from scratch (foundations are solid)
- Adding new log categories or changing the category system
- Adding Error Boundaries (separate task)
- Migrating the 78 direct `console.log` calls (separate task, quick follow-up)

---

## Phase 1: Fix Security (Active Leak)

Priority: **Immediate.** JWT tokens are being logged in plaintext to both console and `frontend.jsonl`.

### 1a. Redact sensitive data in `frontendLogger`

The `ArchitecturalLogger` wrapper has PII redaction, but `frontendLogger` itself does not — and 82 files import `frontendLogger` directly. The JWT appears in two places in the logs:
- `network.request()` → `data.requestData` containing `{"token":"eyJ..."}`
- `APIService` adapter log → `data.requestBody` containing the same token

**Change:** Add a `sanitize()` method to `FrontendLogger` that runs **before both console output and backend queueing** (i.e., at the top of `log()`, before the console switch block at line 488):

```typescript
private readonly SENSITIVE_KEYS = new Set([
  'token', 'password', 'secret', 'credential', 'authorization', 'cookie',
  'api_key', 'apikey', 'access_token', 'refresh_token',
]);
// Note: 'key' excluded — too generic (conflicts with 'cacheKey', 'outputKeys', etc.)

private readonly JWT_PATTERN = /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g;

private sanitize(obj: any, depth = 0): any {
  if (depth > 5 || obj === null || obj === undefined) return obj;
  if (typeof obj === 'string') return obj.replace(this.JWT_PATTERN, '[REDACTED_JWT]');
  if (Array.isArray(obj)) return obj.map(item => this.sanitize(item, depth + 1));
  if (typeof obj === 'object') {
    const result: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (this.SENSITIVE_KEYS.has(k.toLowerCase())) {
        result[k] = '[REDACTED]';
      } else {
        result[k] = this.sanitize(v, depth + 1);
      }
    }
    return result;
  }
  return obj;
}
```

Apply in `log()` method before console output:
```typescript
private log(logData: LogData): void {
  if (!this.isEnabled) return;
  // Sanitize data FIRST — before console and before queue
  if (logData.data) {
    logData.data = this.sanitize(logData.data);
  }
  // ... rest of existing log() body
}
```

**Design notes:**
- Depth limit of 5 prevents stack overflow on circular references
- `key` excluded from sensitive list to avoid false positives on `cacheKey`, `outputKeys`, etc.
- JWT pattern requires 10+ chars per segment to avoid false positives on short base64 strings
- Sanitize runs on the `data` field only (not `message` or `component`) to minimize performance impact

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

**Validation:**
- Log in via Google OAuth, verify `frontend.jsonl` contains `[REDACTED_JWT]` not the actual token
- Verify `cacheKey`, `outputKeys` fields are NOT redacted
- Verify console output also shows redacted tokens
- Test with nested objects: `{auth: {token: "eyJ..."}}` → `{auth: {token: "[REDACTED]"}}`
- Test with stringified JSON in data: `{body: '{"token":"eyJ..."}'}` → JWT pattern caught in string value

---

## Phase 2: Kill the Noise (Suppression & Dedup)

### 2a. Suppress EventBus / UnifiedAdapterCache transform spam

The single biggest noise source. Every EventBus emission logs "Starting data transformation" + "Data transformation successful" per subscriber. A single cache update with 10 subscribers = 20 log lines saying nothing useful. Measured at ~3,300 lines (~43% of total volume).

**Change:** In `frontendLogger.ts`, add a suppression system with periodic summary emission:

```typescript
private readonly SUPPRESSED_COMPONENTS = new Set(['EventBus', 'UnifiedAdapterCache']);
private readonly SUPPRESSED_MESSAGES = new Set([
  'Starting data transformation',
  'Data transformation successful',
]);
private suppressionCounts = new Map<string, number>(); // component → count
private lastSuppressionFlush = Date.now();
private readonly SUPPRESSION_FLUSH_INTERVAL_MS = 30_000; // 30s

// Feature flag — can disable suppression for debugging
private suppressionEnabled = true;
public setSuppression(enabled: boolean): void { this.suppressionEnabled = enabled; }
```

In `log()`, before console/queue:
```typescript
if (this.suppressionEnabled
    && logData.component
    && this.SUPPRESSED_COMPONENTS.has(logData.component)
    && this.SUPPRESSED_MESSAGES.has(logData.message)) {
  const key = logData.component;
  this.suppressionCounts.set(key, (this.suppressionCounts.get(key) ?? 0) + 1);
  this.maybeFlushSuppressionSummary();
  return; // Drop this log
}
```

`maybeFlushSuppressionSummary()` emits a single line every 30s:
```typescript
private maybeFlushSuppressionSummary(): void {
  const now = Date.now();
  if (now - this.lastSuppressionFlush < this.SUPPRESSION_FLUSH_INTERVAL_MS) return;
  if (this.suppressionCounts.size === 0) return;
  const summary = Object.fromEntries(this.suppressionCounts);
  this.suppressionCounts.clear();
  this.lastSuppressionFlush = now;
  this.log({
    level: 'debug',
    category: 'performance',
    message: 'Suppressed log summary',
    component: 'FrontendLogger',
    data: { suppressed: summary, window_s: this.SUPPRESSION_FLUSH_INTERVAL_MS / 1000 },
  });
}
```

**Why suppress rather than fix call sites:** The call sites (EventBus, UnifiedAdapterCache) use `adapter.transformStart/Success` correctly — the problem is that these components fire hundreds of times per user action due to pub/sub fan-out. Fixing the call sites would require architectural changes to the event system, which is out of scope. Suppression at the logger level is the right tradeoff.

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`
**Lines saved:** ~3,300/day (43% of current volume)

### 2b. Deduplicate React re-render logs

`component.mounted` fires 3-6x per component per render cycle due to React StrictMode double-rendering and re-renders. Same component, same message, within milliseconds.

**Change:** Add a bounded dedup window for component lifecycle logs only:

```typescript
private readonly DEDUP_WINDOW_MS = 500;
private readonly DEDUP_MAX_ENTRIES = 100; // Bounded memory
private readonly DEDUP_CATEGORIES = new Set(['component']); // Only dedup component lifecycle
private recentLogs = new Map<string, number>(); // key → timestamp

private isDuplicate(logData: LogData): boolean {
  // Only dedup component lifecycle events
  if (!this.DEDUP_CATEGORIES.has(logData.category)) return false;
  // Only dedup mount/unmount, not state changes (which may carry different data)
  if (logData.message !== 'Component mounted' && logData.message !== 'Component unmounted') return false;

  const key = `${logData.component}:${logData.message}`;
  const now = Date.now();
  const lastSeen = this.recentLogs.get(key);

  if (lastSeen && (now - lastSeen) < this.DEDUP_WINDOW_MS) {
    return true; // Duplicate — skip
  }

  // Prune if at capacity
  if (this.recentLogs.size >= this.DEDUP_MAX_ENTRIES) {
    // Delete oldest entries (first N)
    const toDelete = Math.floor(this.DEDUP_MAX_ENTRIES / 4);
    const iter = this.recentLogs.keys();
    for (let i = 0; i < toDelete; i++) {
      const k = iter.next().value;
      if (k) this.recentLogs.delete(k);
    }
  }

  this.recentLogs.set(key, now);
  return false;
}
```

**Design notes:**
- Only dedup `component.mounted` and `component.unmounted` — NOT `stateChange` (which may carry legitimately different old/new state)
- Bounded to 100 entries with 25% eviction when full
- 500ms window matches typical React StrictMode double-render timing
- Feature flag not needed — dedup is narrow enough to be safe

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`
**Lines saved:** ~500-800/day

### 2c. Silence cache warming when no work done

Cache warming runs every 60 seconds. When all cache hits (the common case after initial load), it logs `cacheWarmingStart` (line 358) + adapter queries + `cacheWarmingComplete` (line 502) for ~20 lines per cycle. Over hours this accumulates.

**Change:** In `frontend/packages/chassis/src/services/CacheWarmer.ts`, add a `silentCycleCount` instance field and gate the start/complete logs on `cacheMisses > 0`:

```typescript
// New instance field:
private silentCycleCount = 0;

// Around line 358 — move cacheWarmingStart AFTER the warming operations complete:
// (Currently it logs start before any work is done — move it to after result is known)

// Around line 502 — replace the unconditional cacheWarmingComplete log:
if (result.cacheMisses === 0) {
  // Silent — no work done. Increment internal counter.
  this.silentCycleCount++;
  // Emit heartbeat every 5 minutes (5 cycles at 60s interval)
  if (this.silentCycleCount % 5 === 0) {
    frontendLogger.info(
      `Cache warming: ${this.silentCycleCount} silent cycles (all cache hits)`,
      'CacheWarmer',
      { portfolioId, silentCycles: this.silentCycleCount }
    );
    this.silentCycleCount = 0;
  }
} else {
  // Actual work done — log start + complete with details
  this.silentCycleCount = 0;
  frontendLogger.user.action('cacheWarmingComplete', 'CacheWarmer', {
    portfolioId,
    success: result.success,
    duration: result.duration,
    dataWarmed: result.dataWarmed,
    cacheHits: result.cacheHits,
    cacheMisses: result.cacheMisses,
  });
}
```

**Files:** `frontend/packages/chassis/src/services/CacheWarmer.ts` (lines 358, 502)
**Lines saved:** ~200-400/day (lower than v1 estimate — Codex counted only ~24 cache warming start/complete pairs in the sample, but each triggers ~20 adapter sub-logs that are already covered by 2a suppression)

---

## Phase 3: Backend Ingestion Alignment

The backend route `routes/frontend_logging.py` overwrites `url` and `userAgent` from HTTP headers, ignoring the frontend payload values. Changes to these fields require updating both sides.

### 3a. Fix `url` field to show route path

**Current behavior:**
- Frontend sends `url: window.location.pathname + window.location.search` (e.g., `/dashboard`)
- Backend overwrites with `request.headers.get('referer', '')` → `http://localhost:3000/` (origin, not route)

**Change (backend):** In `routes/frontend_logging.py`, use the frontend's `url` field if present, fall back to Referer header:

```python
# In process_individual_log():
# Before (line 391):
url = request.headers.get('referer', '')

# After:
url = log_entry.url or request.headers.get('referer', '')
```

**Change (frontend):** Verify `frontendLogger.ts` sends `window.location.pathname` (it already does at line 471 — `url: window.location.pathname + window.location.search`). No change needed.

**Files:** `routes/frontend_logging.py`

### 3b. Stop repeating `userAgent` on every stored log line

**Current behavior:** Backend writes `request.headers.get('user-agent', '')` (~400 bytes) on every line in `structured_event`. This is the same string for every log from the same browser session.

**Change (backend):** In `routes/frontend_logging.py`, replace per-event `userAgent` with the frontend's `session` ID. The `userAgent` can be looked up from the session-start log if needed:

```python
# In process_individual_log(), structured_event dict:
# Before:
"userAgent": request.headers.get('user-agent', ''),

# After:
# userAgent removed from per-event storage — logged once at session start
```

**Change (frontend):** In `frontendLogger.ts`, emit a `session_start` event in the constructor:

```typescript
constructor() {
  // ... existing init ...
  // Emit session start with metadata that only needs to be logged once
  this.log({
    level: 'info',
    category: 'performance',
    message: 'Session started',
    component: 'FrontendLogger',
    data: {
      userAgent: navigator.userAgent,
      screenSize: `${window.innerWidth}x${window.innerHeight}`,
      pathname: window.location.pathname,
    },
  });
}
```

Also stop including `userAgent` in every payload (remove from `log()` method, line 472).

**Files:** `routes/frontend_logging.py`, `frontend/packages/chassis/src/services/frontendLogger.ts`
**Bytes saved:** ~3MB/day in `frontend.jsonl`

### 3c. Strip `architecturalContext` from frontend payload

**Current behavior:** `architecturalContext` and `aiAnalysisHint` are computed on every log call but the backend already ignores them (not in `structured_event`). They still add ~200 bytes per network request from frontend to backend, and clutter console output.

**Change (frontend):** In `log()`, skip computing `architecturalContext` entirely. Remove the `getArchitecturalContext()` call and the `aiAnalysisHint` field from the payload. The session summary and error context (Phase 5) provide better AI debugging value.

Keep `getArchitecturalContext()` and related code as dead code for now (can be deleted in a follow-up cleanup).

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

---

## Phase 4: Make Data Semantic

### 4a. Replace numeric `outputKeys`/`inputKeys` with summaries

Currently: `{"outputKeys": ["0","1","2",...,"46"]}` — just array indices, tells you nothing.

**Change:** In `adapter.transformStart()` and `adapter.transformSuccess()`, change data shape:

```typescript
// Before
data: { inputKeys: Object.keys(inputData ?? {}) }

// After
data: {
  itemCount: Array.isArray(inputData) ? inputData.length : Object.keys(inputData ?? {}).length,
  type: Array.isArray(inputData) ? 'array' : 'object',
  // Only include actual keys for objects (not array indices), capped at 10
  ...((!Array.isArray(inputData) && inputData) ? { keys: Object.keys(inputData).slice(0, 10) } : {})
}
```

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

### 4b. Add operation context to adapter logs

Currently `"Starting data transformation"` with no indication of WHAT is being transformed. Call sites pass meaningful strings to `adapterName` but the message is always generic.

**Change:** Add an optional `operation` parameter to `adapter.transformStart()` / `adapter.transformSuccess()`:

```typescript
transformStart: (adapterName: string, inputData: any, operation?: string) => {
  this.log({
    message: operation ? `Transform: ${operation}` : 'Starting data transformation',
    component: adapterName,
    // ...
  });
},

transformSuccess: (adapterName: string, outputData: any, operation?: string) => {
  this.log({
    message: operation ? `Transform complete: ${operation}` : 'Data transformation successful',
    component: adapterName,
    // ...
  });
},
```

Backward-compatible — existing call sites continue to work unchanged. New/updated call sites can add context like `frontendLogger.adapter.transformStart('RiskScoreAdapter', data, 'risk-score-api-response')`.

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

### 4c. Fix `component: "Unknown"` on network logs

Every `network.request()` and `network.response()` logs `component: "Unknown"` because the caller doesn't pass its identity.

**Change:** Add an optional `component` parameter to `network.request()` and `network.response()`. Default to `"APIService"` (the known primary caller) rather than inferring from URL path (which can misattribute):

```typescript
request: (url: string, method: string, data?: any, component?: string) => {
  this.log({
    level: 'debug',
    category: 'network',
    message: `${method} request to ${url}`,
    component: component || 'APIService',
    data: { url, method, requestData: data },
  });
},

response: (url: string, status: number, responseTime: number, component?: string) => {
  // ...
  component: component || 'APIService',
},
```

Update `APIService.ts` to pass `'APIService'` explicitly (or let the default work).

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`, `frontend/packages/chassis/src/services/APIService.ts`

### 4d. Truncate large request/response bodies

Some adapter logs include full API response bodies (e.g., line 3047 with 73KB risk score response dumped into `data`). These bloat the log file and are not useful for debugging.

**Change:** In `log()`, truncate `data` values that exceed a threshold:

```typescript
private readonly MAX_DATA_VALUE_LENGTH = 500; // chars per string value

private truncateData(obj: any, depth = 0): any {
  if (depth > 5 || obj === null || obj === undefined) return obj;
  if (typeof obj === 'string' && obj.length > this.MAX_DATA_VALUE_LENGTH) {
    return obj.substring(0, this.MAX_DATA_VALUE_LENGTH) + `...[truncated, ${obj.length} chars]`;
  }
  if (Array.isArray(obj) && obj.length > 20) {
    return [...obj.slice(0, 20), `...[${obj.length - 20} more items]`];
  }
  if (typeof obj === 'object') {
    const result: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      result[k] = this.truncateData(v, depth + 1);
    }
    return result;
  }
  return obj;
}
```

Apply in `log()` after `sanitize()`, before console/queue.

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

---

## Phase 5: Agent-Oriented Features

### 5a. Session summary log

Emit a structured summary periodically (every 5 minutes) and on `beforeunload` with aggregate stats. Use `navigator.sendBeacon()` for the unload case to ensure delivery:

```typescript
private sessionStats = {
  apiCalls: 0,
  apiErrors: 0,
  totalResponseMs: 0,
  slowestCall: null as { url: string; duration_ms: number } | null,
  userActions: 0,
  warnings: 0,
  errors: 0,
  cacheHits: 0,
  cacheMisses: 0,
  viewsVisited: new Set<string>(),
};

// Increment stats in relevant log methods (network.response, user.action, etc.)
// Emit summary:
private emitSessionSummary(): void {
  const stats = this.sessionStats;
  this.log({
    level: 'info',
    category: 'performance',
    message: 'Session summary',
    component: 'FrontendLogger',
    data: {
      duration_s: Math.round((Date.now() - this.sessionStartTime) / 1000),
      api_calls: stats.apiCalls,
      api_errors: stats.apiErrors,
      avg_response_ms: stats.apiCalls > 0 ? Math.round(stats.totalResponseMs / stats.apiCalls) : 0,
      slowest_call: stats.slowestCall,
      user_actions: stats.userActions,
      warnings: stats.warnings,
      errors: stats.errors,
      cache_hit_rate: (stats.cacheHits + stats.cacheMisses) > 0
        ? Math.round(stats.cacheHits / (stats.cacheHits + stats.cacheMisses) * 100) / 100
        : null,
      views_visited: [...stats.viewsVisited],
    },
  });
}

// In constructor:
this.sessionStartTime = Date.now();
setInterval(() => this.emitSessionSummary(), 5 * 60 * 1000); // Every 5 min
window.addEventListener('beforeunload', () => {
  const payload = /* build summary payload */;
  navigator.sendBeacon(`${this.baseUrl}/api/log-frontend`, JSON.stringify(payload));
});
```

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

### 5b. Error context enrichment

When an error is logged, automatically attach recent context so the agent doesn't have to correlate manually.

**Change:** Maintain a bounded ring buffer of recent meaningful log summaries:

```typescript
private readonly CONTEXT_BUFFER_SIZE = 10;
private contextBuffer: string[] = [];

// In log(), after suppression/dedup checks, before queueing:
if (logData.level !== 'debug') { // Only track non-debug logs
  const summary = `${logData.component || 'App'}: ${logData.message}`;
  this.contextBuffer.push(summary);
  if (this.contextBuffer.length > this.CONTEXT_BUFFER_SIZE) {
    this.contextBuffer.shift(); // Drop oldest
  }
}

// When logging errors, attach context:
if (logData.level === 'error') {
  logData.data = {
    ...logData.data,
    recentContext: [...this.contextBuffer],
  };
}
```

**Design notes:**
- Ring buffer capped at 10 entries — bounded memory, no pruning needed
- Only non-debug logs tracked (debug logs are noise)
- Context is a string summary, not the full log payload (keeps error log readable)

**Files:** `frontend/packages/chassis/src/services/frontendLogger.ts`

---

## Implementation Order

| Step | Item | Impact | Risk |
|------|------|--------|------|
| 1 | **1a** Security: Redact auth tokens | Fix active JWT leak | Low — sanitize before console+queue |
| 2 | **2a** Suppress EventBus/Cache spam | ~3,300 lines/day removed (43%) | Low — feature flag to disable |
| 3 | **2b** Dedup React re-renders | ~500-800 lines removed | Low — narrow scope (mount/unmount only) |
| 4 | **2c** Silence idle cache warming | ~200-400 lines removed | Low — call site change |
| 5 | **3a** Fix url field (backend) | Correct route in stored logs | Low — backend route change |
| 6 | **3b** Stop repeating userAgent (backend+frontend) | ~3MB/day saved | Low — session_start event |
| 7 | **3c** Strip architecturalContext | Smaller payloads, less console noise | None — backend already ignores |
| 8 | **4a** Semantic data keys | Readable data fields | None — same API |
| 9 | **4b** Operation context on transforms | Better traceability | None — optional param |
| 10 | **4c** Fix Unknown network component | Better attribution | None — backward compatible |
| 11 | **4d** Truncate large data values | Prevent log bloat | Low — only truncates display |
| 12 | **5a** Session summary | Agent-oriented overview | Low — additive |
| 13 | **5b** Error context enrichment | Faster debugging | Low — bounded ring buffer |

## Expected Outcome

- **Before:** 7,602 lines / 4.2MB per day, ~43% pure EventBus noise
- **After:** ~2,500-3,000 lines / ~800KB per day, high signal density
- **Agent experience:** Can scan a session in seconds via summary log, find errors with auto-attached context, understand user flow without wading through EventBus spam
- **Security:** No more plaintext auth tokens in logs (console or stored)
- **Backward compatibility:** All 82 importing files compile with zero changes

## Validation

### Functional
- Run dev server, complete a full user flow (login → dashboard → navigate views → logout)
- Compare line counts before/after (target: ~60-70% reduction)
- Verify no auth tokens appear in `frontend.jsonl` or browser console
- Verify `cacheKey`, `outputKeys` fields are NOT redacted (no false positives)
- Verify meaningful events (API calls, errors, user actions) are still logged
- Verify session summary is emitted every 5 min and on page unload
- Verify error logs include `recentContext` array
- Verify suppression summary is emitted every 30s when transforms are suppressed
- Spot-check that the 82 importing files compile with no changes

### Security
- Test with nested objects: `{auth: {token: "eyJ..."}}` → `{auth: {token: "[REDACTED]"}}`
- Test with stringified JSON containing JWT → pattern caught in string values
- Test with `{cacheKey: "foo", apiKey: "bar"}` → only `apiKey` redacted
- Verify sanitization runs before console output (not just before queue)

### Regression
- Verify real errors (component errors, network 4xx/5xx, adapter transform failures) are never suppressed
- Verify suppression feature flag `setSuppression(false)` restores full logging
- Verify dedup only affects `component.mounted`/`component.unmounted`, not `stateChange`
- Verify `beforeunload` summary is delivered via `sendBeacon`

### Performance
- Verify sanitize + truncate + dedup overhead is negligible (<1ms per log call)
- Verify ring buffer and dedup map stay bounded (no memory leak over long sessions)
