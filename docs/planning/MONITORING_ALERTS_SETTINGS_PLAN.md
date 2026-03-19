# Replace Placeholder Monitoring & Alerts Tabs with Real Settings

## Context
The Risk Settings view has 3 tabs: Risk Limits (functional), Monitoring (placeholder), Alerts (placeholder). The Monitoring and Alerts tabs have fake toggles (email/SMS/real-time) that aren't connected to any backend. We're replacing them with controls that actually affect app behavior — Smart Alert thresholds and Market Intelligence preferences.

## Decisions
- **API**: Extend existing `/api/risk-settings` — store monitoring settings in `additional_settings` JSONB
- **Tab layout**: Keep two tabs, rewire both with real controls

## Architecture Notes
The `additional_settings` JSONB column exists in the risk_limits DB table. The manager preserves it through save/load. However:
- The backend API flattens `additional_settings` via `to_dict()` (`data_objects.py:1439`)
- The frontend adapter only reads `portfolio_limits`, `concentration_limits`, `variance_limits` — strips everything else
- The adapter's `transformForBackend()` doesn't include `additional_settings`, so it's **lost on save**
- The container filters to scalar values, dropping nested objects
- The view uses flat key-value state

These gaps all need addressing.

## Correct Threshold Values (from `core/position_flags.py`)
- Single position concentration: **>15%** (line 126)
- Leveraged single-stock: **>25%** equity weight (line 142)
- Top 5 concentration: **>60%** (line 166)
- Large fund position: **>30%** (line 179) — NOT sector concentration
- High leverage: **>2.0x** (line 190), info leverage: **>1.1x** (line 199)
- **Sector concentration: >40%** (line 397) — this is the real sector alert

## Files to Modify

### Backend

#### 1. `core/position_flags.py` — Accept threshold overrides

Add optional `thresholds: dict | None = None` parameter to `generate_position_flags()`:
```python
t = thresholds or {}
single_position_pct = t.get("position_concentration", 15.0)
top5_pct = t.get("top5_concentration", 60.0)
sector_pct = t.get("sector_concentration", 40.0)
leverage_info = t.get("leverage_warning", 1.1)
leverage_high = t.get("leverage_high", 2.0)
```
Replace hardcoded values at lines 126, 166, 190, 199, 397 with these variables.

#### 2. All `generate_position_flags()` call sites — Thread thresholds

Call sites (all need `thresholds=` kwarg):
- `routes/positions.py:426` — REST holdings enrichment
- `routes/positions.py:637` — REST alerts endpoint
- `mcp_tools/positions.py:397` — MCP positions tool
- `mcp_tools/metric_insights.py:139` — metric insights builder

At each call site, load user's monitoring settings from risk limits `additional_settings` and pass as `thresholds=`. Use a shared helper:
```python
def _load_user_alert_thresholds(user_id: int) -> dict | None:
    """Load monitoring thresholds from risk_limits additional_settings."""
    try:
        manager = RiskLimitsManager(use_database=True, user_id=user_id)
        limits = manager.load_risk_limits()
        additional = getattr(limits, 'additional_settings', None) or {}
        return additional.get("monitoring")
    except Exception:
        return None
```

#### 3. `routes/positions.py` — Thread market intelligence prefs

In `_build_cached_market_intelligence_payload()` (~line 189), load user's monitoring settings and pass `news_limit`, `earnings_days`, `max_events` to both the cache key and the builder call. The cache key must include these values to avoid serving stale cached results with old preferences.

#### 4. `portfolio_risk_engine/data_objects.py` — Fix `to_dict()` flattening

The `to_dict()` method at line ~1439 does `result.update(self.additional_settings)` which flattens the nested dict. Instead, preserve it as a nested key:
```python
if self.additional_settings:
    result["additional_settings"] = self.additional_settings
```
This ensures the API response includes `additional_settings` as a proper nested object that the frontend can read.

### Frontend

#### 5. `frontend/packages/connectors/src/adapters/RiskSettingsAdapter.ts`

**In `performTransformation()` (~line 269):** Extract monitoring settings from `_original_backend_data` (which has the raw backend response):
```typescript
const additionalSettings = backendRiskLimits.additional_settings ?? backendRiskLimits;
const monitoringSettings = (typeof additionalSettings.monitoring === 'object' && additionalSettings.monitoring) || {};

// Add to transformedRiskLimits:
position_concentration_alert: monitoringSettings.position_concentration ?? 15,
top5_concentration_alert: monitoringSettings.top5_concentration ?? 60,
sector_concentration_alert: monitoringSettings.sector_concentration ?? 40,
leverage_warning: monitoringSettings.leverage_warning ?? 1.1,
news_limit: monitoringSettings.news_limit ?? 8,
earnings_lookahead_days: monitoringSettings.earnings_lookahead_days ?? 14,
max_market_events: monitoringSettings.max_market_events ?? 12,
```

These are flat scalar values (not nested objects) so the container won't filter them out.

**In `transformForBackend()` (~line 366):** Add an optional `existingAdditionalSettings` parameter to receive preserved backend state:
```typescript
transformForBackend(uiSettings: unknown, existingAdditionalSettings?: Record<string, unknown>): Record<string, unknown> {
  ...
  const backendSettings = {
    portfolio_limits: { ... },
    concentration_limits: { ... },
    variance_limits: { ... },
    max_single_factor_loss: ...,
    additional_settings: {
      ...(existingAdditionalSettings ?? {}),  // preserve profile, derived_at, etc.
      monitoring: {
        position_concentration: uiSettingsRecord.position_concentration_alert,
        top5_concentration: uiSettingsRecord.top5_concentration_alert,
        sector_concentration: uiSettingsRecord.sector_concentration_alert,
        leverage_warning: uiSettingsRecord.leverage_warning,
        news_limit: uiSettingsRecord.news_limit,
        earnings_lookahead_days: uiSettingsRecord.earnings_lookahead_days,
        max_market_events: uiSettingsRecord.max_market_events,
      },
    },
  };
}
```

#### 5b. `frontend/packages/connectors/src/features/riskSettings/hooks/useRiskSettings.ts` — Preserve additional_settings

The hook fetches risk settings and calls the adapter. The container then filters `risk_limits` to scalars (dropping `_original_backend_data`). To preserve `additional_settings` for the save path:

Sync the original `additional_settings` from query data (covers both fresh fetch and TanStack cache hits). Reset on every data/portfolio change to avoid stale cross-portfolio bleed:
```typescript
const additionalSettingsRef = useRef<Record<string, unknown>>({});

// Sync whenever query data or portfolio changes — always reset
useEffect(() => {
  const next = data?.risk_limits?._original_backend_data?.additional_settings;
  additionalSettingsRef.current = next && typeof next === 'object' ? next as Record<string, unknown> : {};
}, [data]);
```

Then in `updateSettings()`, pass it to `transformForBackend()`:
```typescript
const backendPayload = adapter.transformForBackend(settings, additionalSettingsRef.current);
```

This ensures existing profile metadata survives the round-trip regardless of whether data came from network or TanStack cache. The `_original_backend_data` is set by the adapter's `transform()` (line 295) and is available on the raw query data before the container filters it to scalars.

#### 6. `frontend/packages/ui/src/components/dashboard/views/modern/RiskSettingsViewModern.tsx`

**Monitoring tab** → "Smart Alert Thresholds":
- Position Concentration Alert: Slider 5-50%, default 15%
- Top 5 Concentration Alert: Slider 30-90%, default 60%
- Sector Concentration Alert: Slider 20-60%, default 40%
- Leverage Warning: Slider 1.0-3.0x (step 0.1), default 1.1x

Remove: Real-time Monitoring toggle, Daily Reports toggle, Monitoring Frequency dropdown, Compliance Status card.

**Alerts tab** → "Market Intelligence Preferences":
- News Articles: Slider 2-15, default 8
- Earnings Lookahead: Dropdown 7/14/30 days, default 14
- Max Events Shown: Slider 4-20, default 12

Remove: Email Alerts toggle, SMS Alerts toggle, Alert Threshold dropdown.

Read values from `settings` object (flat scalars like `position_concentration_alert`), write via `handleSettingChange()` (same pattern as existing Risk Limits tab).

## Data Shape (stored in `additional_settings.monitoring`)

```json
{
  "position_concentration": 15.0,
  "top5_concentration": 60.0,
  "sector_concentration": 40.0,
  "leverage_warning": 1.1,
  "news_limit": 8,
  "earnings_lookahead_days": 14,
  "max_market_events": 12
}
```

## What Changes for the User
1. **Monitoring tab**: Sliders to tune Smart Alert sensitivity (concentration, leverage thresholds)
2. **Alerts tab**: Controls for Market Intelligence volume (news count, earnings window, max events)
3. **Settings persist** in DB via `additional_settings` JSONB — survive refresh, per-user
4. **Fake controls removed** — no more email/SMS/real-time toggles that do nothing

## Verification
1. Frontend: `npx tsc --noEmit` across connectors + ui packages
2. Backend: `python3 -m pytest tests/core/test_position_flags.py -v`
3. Chrome: Settings → Monitoring tab → adjust position concentration slider to 25% → save → Overview → verify Smart Alerts use new threshold
4. Chrome: Settings → Alerts tab → set news limit to 4 → save → verify Market Intelligence shows fewer items
5. Refresh page → verify settings persist
6. Verify existing risk limit saves still work (no data loss on round-trip)
