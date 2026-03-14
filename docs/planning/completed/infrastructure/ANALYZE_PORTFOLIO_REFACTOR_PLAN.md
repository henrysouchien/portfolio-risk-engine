# Refactor: Make analyze_portfolio() Accept PortfolioData Directly

## Problem
Three paths feed into risk analysis, all forced through YAML file paths:
1. **CLI**: YAML file → `analyze_portfolio(filepath)` — works fine
2. **API/Service**: `PortfolioData` → `create_temp_file()` → `analyze_portfolio(temp_filepath)` → delete — wasteful round-trip
3. **Positions CLI**: `PositionData.to_portfolio_data()` [incomplete — no factor proxies] → `create_temp_file()` → `run_portfolio(temp_filepath)` → **CRASHES** on empty beta DataFrame

## Goal
- `analyze_portfolio()` accepts a `PortfolioData` object directly (no temp files needed)
- CLI path stays unchanged (filepath → `PortfolioData.from_yaml()` → same pipeline)
- Fix the empty beta crash
- Fix the incomplete `PositionData.to_portfolio_data()` path

---

## Step 1: Fix the crash — guard empty beta rows
**File**: `run_portfolio_risk.py` (line 622)

`evaluate_portfolio_beta_limits()` crashes when `rows` is empty (no factor proxies). Add early return:
```python
if not rows:
    df = pd.DataFrame(columns=["portfolio_beta", "max_allowed_beta", "pass", "buffer"])
    df.index.name = "factor"
    return df
```

> **Review fix #2 (High):** The early-return DataFrame must have `index.name = "factor"` to preserve output shape. Downstream code calls `df_beta.reset_index()` which expects a `factor` column — without the index name it would produce an `index` column instead.

This is a bug fix independent of the refactor — makes the system resilient to portfolios without factor proxies.

---

## Step 2: Refactor `calc_max_factor_betas()` to accept dicts
**File**: `risk_helpers.py` (line 201)

Currently reads YAML just to extract `stock_factor_proxies`, `fmp_ticker_map`, and `max_single_factor_loss`. Change signature to accept these as optional kwargs:

```python
def calc_max_factor_betas(
    portfolio_yaml: str = "portfolio.yaml",  # Keep original default for backward compat
    risk_yaml: str = "risk_limits.yaml",
    lookback_years: int = None,
    echo: bool = True,
    *,
    stock_factor_proxies: Optional[Dict] = None,   # NEW
    fmp_ticker_map: Optional[Dict] = None,          # NEW
    max_single_factor_loss: Optional[float] = None,  # NEW
):
```

> **Review fix R2-1 (Medium):** Keep `portfolio_yaml` default as `"portfolio.yaml"` (not `None`). Changing it to `None` would break existing no-arg callers (docs, ad-hoc usage). The kwarg-takes-precedence logic still works — when `stock_factor_proxies` is provided, the file is simply never read regardless of the default.

Logic: if `stock_factor_proxies` is provided, skip reading `portfolio_yaml`. If `max_single_factor_loss` is provided, skip reading `risk_yaml`. Fall back to file reads when kwargs are `None`.

> **Review fix #4 (Medium):** Must explicitly handle precedence and edge cases:
> - `stock_factor_proxies={}` counts as "provided" — skip file read, return early (no proxies to analyze).
> - `stock_factor_proxies=None` and `portfolio_yaml=None` → raise `ValueError` (cannot read from `None` path).
> - Same logic for `max_single_factor_loss` vs `risk_yaml`.
>
> Guard implementation (note: default is `"portfolio.yaml"` so the `elif` branch covers no-arg callers; the `is not None` check ensures we never `open(None, ...)`):
> ```python
> # Resolve proxies: kwarg takes precedence over file
> if stock_factor_proxies is not None:
>     proxies = stock_factor_proxies
>     fmp_map = fmp_ticker_map  # may be None, that's fine
> elif portfolio_yaml is not None:
>     with open(portfolio_yaml, "r") as f:
>         port_cfg = yaml.safe_load(f)
>     proxies = port_cfg["stock_factor_proxies"]
>     fmp_map = port_cfg.get("fmp_ticker_map")
> else:
>     raise ValueError("Must provide stock_factor_proxies or portfolio_yaml")
>
> # Resolve loss limit: kwarg takes precedence over file
> if max_single_factor_loss is not None:
>     loss_limit = max_single_factor_loss
> else:
>     with open(risk_yaml, "r") as f:
>         risk_cfg = yaml.safe_load(f)
>     loss_limit = risk_cfg["max_single_factor_loss"]
>
> # Early return if no proxies to analyze
> if not proxies:
>     empty_analysis = {
>         "worst_per_proxy": {},
>         "worst_by_factor": {},
>         "analysis_period": {"start": None, "end": None, "years": lookback_years},
>         "loss_limit": loss_limit,
>     }
>     return {}, {}, empty_analysis
> ```
>
> **Review fix R2-4 (Low):** The early-return `historical_analysis` dict must include all expected keys (`worst_per_proxy`, `worst_by_factor`, `analysis_period`, `loss_limit`) — some downstream consumers access these unconditionally. Use `None`/empty values rather than omitting keys.

---

## Step 3: Refactor `analyze_portfolio()` to accept PortfolioData
**File**: `core/portfolio_analysis.py`

Change signature from:
```python
def analyze_portfolio(filepath: str, risk_yaml: str = "risk_limits.yaml", *, asset_classes=None)
```
To:
```python
def analyze_portfolio(
    portfolio: Union[str, PortfolioData],
    risk_yaml: str = "risk_limits.yaml",
    *,
    asset_classes: Optional[Dict[str, str]] = None,
) -> RiskAnalysisResult:
```

Internal logic:
```python
if isinstance(portfolio, str):
    # Legacy filepath path — load from YAML
    config = load_portfolio_config(portfolio)
    filepath = portfolio
else:
    # PortfolioData path — extract fields directly
    config = _config_from_portfolio_data(portfolio)
    filepath = None  # No file to reference
```

Add a helper `_config_from_portfolio_data(pd: PortfolioData) -> dict` that builds the same config dict that `load_portfolio_config()` returns, using PortfolioData fields + `standardize_portfolio_input()` for weights/exposure.

> **Review fix #3 (Medium):** `_config_from_portfolio_data()` must use `portfolio_data.standardized_input` (not raw `portfolio_input`) when building the config's `portfolio_input` field. Raw input may be numeric weights/percentages that `standardize_portfolio_input()` can't handle without the original format context. If `standardized_input` is available, use it directly; otherwise fall back to `portfolio_input`.

> **Review fix R2-2 (Medium):** `_config_from_portfolio_data()` must set `config["name"]` from `portfolio_data.portfolio_name`. Without this, `analysis_metadata["portfolio_name"]` (which uses `config.get("name", "Portfolio")`) will always show the generic "Portfolio" string for PortfolioData inputs — a data-loss regression.

> **Review fix #6 (Low):** `analysis_metadata["portfolio_file"]` must not become a PortfolioData object — downstream serialization (JSON for API, logging) would break. Set to `None` (or a descriptive string like the portfolio name) when the input is not a filepath:
> ```python
> "portfolio_file": filepath,  # already None for PortfolioData path
> ```

For `calc_max_factor_betas`, pass the dicts directly (from Step 2) instead of `filepath`:
```python
max_betas, max_betas_by_proxy, historical_analysis = calc_max_factor_betas(
    risk_yaml=risk_yaml,
    lookback_years=lookback_years,
    echo=False,
    stock_factor_proxies=config.get("stock_factor_proxies"),
    fmp_ticker_map=config.get("fmp_ticker_map"),
    max_single_factor_loss=risk_config.get("max_single_factor_loss"),
)
```

---

## Step 4: Update `run_risk.py` `run_portfolio()` to accept PortfolioData
**File**: `run_risk.py` (line 236)

Change signature:
```python
def run_portfolio(
    filepath: Union[str, PortfolioData],
    risk_yaml: str = "risk_limits.yaml",
    *,
    return_data: bool = False,
    asset_classes: Optional[Dict[str, str]] = None,
) -> Union[None, RiskAnalysisResult]:
```

Pass `filepath` (which may be a PortfolioData) straight through to `analyze_portfolio()`.

> **Review fix #1 (High):** The CLI path (`return_data=False`, lines 334-337) calls `load_portfolio_config(filepath)` and `display_portfolio_config(config)` for display. When `filepath` is a PortfolioData, `load_portfolio_config()` will crash (it expects a file path string). Must branch:
> ```python
> if return_data:
>     return result
> else:
>     # CLI MODE: display config then report
>     if isinstance(filepath, str):
>         from run_portfolio_risk import load_portfolio_config, display_portfolio_config
>         config = load_portfolio_config(filepath)
>         display_portfolio_config(config)
>     else:
>         # PortfolioData — build display config from the object
>         from run_portfolio_risk import display_portfolio_config
>         config = _config_from_portfolio_data(filepath)  # reuse helper from Step 3
>         display_portfolio_config(config)
>     print(result.to_cli_report())
> ```
> This matters because `run_positions.py --to-risk` defaults to `return_data=False`.

> **Review fix #5 (Medium):** Asset class derivation (lines 312-320) currently calls `load_portfolio_config(filepath)` then `standardize_portfolio_input()` to get tickers. For PortfolioData input, use `portfolio_data.get_tickers()` instead — `get_weights()` returns `{}` when input is shares/dollars:
> ```python
> if asset_classes is None:
>     try:
>         if isinstance(filepath, str):
>             config = load_portfolio_config(filepath)
>             weights = config.get("weights") or standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
>             tickers = list(weights.keys())
>         else:
>             tickers = filepath.get_tickers()
>         from services.security_type_service import SecurityTypeService
>         asset_classes = SecurityTypeService.get_asset_classes(tickers)
>     except Exception:
>         asset_classes = None
> ```

---

## Step 5: Update `services/portfolio_service.py` to skip temp files
**File**: `services/portfolio_service.py` (line 228)

Replace:
```python
temp_portfolio_file = portfolio_data.create_temp_file()
try:
    result = run_portfolio(temp_portfolio_file, ...)
finally:
    os.unlink(temp_portfolio_file)
```
With:
```python
result = run_portfolio(portfolio_data, ...)
```

Keep `temp_risk_file` handling as-is for now (risk limits refactor is a separate concern). When `risk_limits_data` is provided, still create a temp file for the risk YAML and pass its path as `risk_yaml=`.

---

## Step 6: Fix `run_positions.py --to-risk` path
**File**: `run_positions.py` (line 74-86)

Two changes:
1. After `to_portfolio_data()`, enrich with factor proxies if user context is available:
```python
portfolio_data = result.data.to_portfolio_data()

# Enrich with factor proxies — resolve user_id from email if needed
user_id = portfolio_data.user_id or service.config.user_id
if not user_id and user_email:
    user_id = service._get_user_id()  # resolves from user_email (hits DB)
    # TODO: expose a public helper for user_id resolution to avoid private method access
if user_id:
    from services.factor_proxy_service import ensure_factor_proxies
    proxies = ensure_factor_proxies(
        user_id=user_id,
        portfolio_name=portfolio_data.portfolio_name or "CURRENT_PORTFOLIO",
        tickers=set(portfolio_data.get_tickers()),
    )
    portfolio_data.stock_factor_proxies = proxies
```

> **Review fix R2-3 (Medium):** `PositionService(user_email=...)` leaves `config.user_id=None` — the email is available but the UUID isn't resolved yet. The original condition (`portfolio_data.user_id or service.config.user_id`) would almost always be `False`, silently skipping proxy enrichment. Must resolve `user_id` from the email via `service._get_user_id()` (or equivalent) before the check.

> **Review fix #7 (Low):** Do NOT pass `allow_gpt=True` — that overrides the global config and would force GPT calls on every CLI run. Omit it (or pass `allow_gpt=None`) to respect the user's global `allow_gpt` setting from config/settings.

2. Pass PortfolioData directly (no temp file):
```python
risk_result = run_portfolio(portfolio_data, return_data=return_data)
```

Remove the `create_temp_file()` / `os.unlink()` block entirely.

---

## Files Modified (in order)
1. `run_portfolio_risk.py` — empty beta guard (Step 1)
2. `risk_helpers.py` — `calc_max_factor_betas()` dict params (Step 2)
3. `core/portfolio_analysis.py` — `analyze_portfolio()` accepts PortfolioData (Step 3)
4. `run_risk.py` — `run_portfolio()` accepts PortfolioData (Step 4)
5. `services/portfolio_service.py` — skip temp file (Step 5)
6. `run_positions.py` — enrich + pass PortfolioData directly (Step 6)

## Review Findings — Round 1 (all addressed above)
| # | Severity | Issue | Addressed In |
|---|----------|-------|--------------|
| 1 | High | `run_portfolio()` CLI path crashes with PortfolioData (`load_portfolio_config(filepath)`) | Step 4 |
| 2 | High | Empty beta guard must preserve `index.name = "factor"` | Step 1 |
| 3 | Medium | `_config_from_portfolio_data()` must use `standardized_input` not raw `portfolio_input` | Step 3 |
| 4 | Medium | `calc_max_factor_betas()` must guard `None`/empty inputs, define precedence | Step 2 |
| 5 | Medium | Asset class derivation must use `get_tickers()` not `get_weights()` for shares/dollars | Step 4 |
| 6 | Low | `analysis_metadata["portfolio_file"]` must not become a PortfolioData object | Step 3 |
| 7 | Low | `ensure_factor_proxies(allow_gpt=True)` overrides global config | Step 6 |

## Review Findings — Round 2
| # | Severity | Issue | Addressed In |
|---|----------|-------|--------------|
| R2-1 | Medium | `portfolio_yaml=None` default breaks existing no-arg callers — keep `"portfolio.yaml"` | Step 2 |
| R2-2 | Medium | `_config_from_portfolio_data()` must set `config["name"]` from `portfolio_name` | Step 3 |
| R2-3 | Medium | `user_id` not resolved from email — proxies silently skipped in CLI | Step 6 |
| R2-4 | Low | Early-return `historical_analysis` must include all expected keys | Step 2 |

## NOT in scope (future work)
- Refactoring `analyze_scenario()`, `optimize_min_variance()`, `optimize_max_return()` — same pattern but separate pass
- Refactoring risk limits YAML handling (RiskLimitsData already exists as a data object)
- Removing `to_yaml()` / `create_temp_file()` methods — still useful for other consumers

## Verification
1. `python3 run_risk.py --portfolio portfolio.yaml` — CLI path still works
2. `python3 run_positions.py --user-email hc@henrychien.com --to-risk` — positions path works end-to-end
3. Run existing tests: `pytest tests/` to check nothing breaks
4. Verify API path via `portfolio_service.py` integration (service layer skips temp files)
