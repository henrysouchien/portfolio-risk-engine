# CLI Setup Wizard + User Config System

> **Status**: PLANNED
> **Created**: 2026-03-19
> **Phase**: C2 (Open Source CLI Launch)
> **Parent**: `docs/OPEN_SOURCE_LAUNCH_GAPS.md`
> **Depends on**: B4 (portfolio-mcp extraction — partial, wizard can precede full extraction)

---

## Problem Statement

A user installs `portfolio-mcp` and hits a wall: they need to know which env vars to set, which YAML files to create, where config files go, and how to verify connectivity. There is no first-run experience. The current setup path requires reading `ENVIRONMENT_SETUP.md`, copying `.env.example`, and manually editing multiple files. This is acceptable for the developer who built the system but is a non-starter for open-source adoption.

The wizard must get a user from `pip install` to a working MCP server with real portfolio data in under 5 minutes.

---

## Current State

| Component | Exists | Location |
|---|---|---|
| Env var loading | Yes | `settings.py` loads `.env` via `dotenv`; `utils/user_context.py` reads `RISK_MODULE_USER_EMAIL` with env + dotenv fallback |
| Config files | Yes | 13 YAML files in `config/` (portfolio, risk limits, strategy templates, mappings) |
| Provider enablement | Yes | `providers/routing.py` — `is_provider_enabled()` / `is_provider_available()` check env vars + credentials |
| Provider credentials | Yes | `settings.PROVIDER_CREDENTIALS` dict maps provider names to required env vars |
| No-DB mode | Yes | `database/__init__.py` — `is_db_available()` positive-only cache; `@require_db` decorator in `mcp_tools/common.py` |
| MCP server env validation | Yes | `mcp_server.py` — `_validate_environment()` checks FMP key, user email, DATABASE_URL on boot |
| CSV import | Yes | `mcp_tools/import_portfolio.py` — multi-format with AI-assisted normalizer builder |
| Normalizer staging dir | Yes | `~/.risk_module/normalizers/` and `~/.risk_module/transaction_normalizers/` |
| FMP API key validation | Partial | `fmp/client.py` raises `FMPAuthenticationError` on missing key but no test-before-save |
| User config directory | No | No `~/.openclaw/` or equivalent |
| CLI wizard | No | Nothing |
| Config file generation | No | No programmatic config generation |
| First-run detection | No | No mechanism to detect "never configured" state |

---

## Design Decisions

### D1: Config home directory

Use `~/.portfolio-mcp/` as the user config directory (matches the package name; rename to `~/.openclaw/` when branding is finalized). Respect `XDG_CONFIG_HOME` on Linux if set, otherwise default to `~/.portfolio-mcp/`.

```python
def get_config_home() -> Path:
    """Resolve user config directory, respecting XDG on Linux."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg and sys.platform == "linux":
        return Path(xdg) / "portfolio-mcp"
    return Path.home() / ".portfolio-mcp"
```

### D2: Config file format

Single `config.yaml` for credentials + settings. Not `.env` — YAML is the established config format in this project (13 files in `config/`), supports nested structures, and avoids confusion with the project-root `.env` used during development.

A `.env` bridge file is generated alongside for backward compatibility with `settings.py` / `dotenv` loading, but the wizard reads/writes YAML as the source of truth.

### D3: No-DB as default

CLI users run without PostgreSQL by default. The wizard does not prompt for `DATABASE_URL` unless the user explicitly opts in. The no-DB mode (Phase A, `ecc66f7d`) already handles this — `@require_db` decorated tools return actionable errors, and all analysis tools work via CSV import + YAML config.

### D4: Provider tier model

The wizard detects the user's tier based on which API keys they configure:

| Tier | Requirements | Unlocks |
|---|---|---|
| **Free** | FMP API key only | Market data, factor analysis, risk scoring, portfolio analysis via CSV import |
| **Pro** | + IBKR credentials (Gateway or Flex) | Live positions, trade history, realized performance, trading |
| **Enterprise** | + Plaid or SnapTrade | Multi-institution aggregation, 10,000+ brokerage support |

This is descriptive (shown as a summary), not prescriptive (nothing is locked). All features are available if the credentials are present.

### D5: Wizard is re-entrant

`portfolio-mcp setup` can be run at any time to reconfigure. It reads existing `config.yaml` and pre-fills values. Individual subsections can be targeted: `portfolio-mcp setup --fmp`, `portfolio-mcp setup --broker`, `portfolio-mcp setup --portfolio`.

### D6: Validation before save

Every API key is validated before writing to config. An invalid FMP key should fail fast with a clear message, not silently produce broken analysis 10 minutes later.

---

## Architecture

### File layout

```
~/.portfolio-mcp/
  config.yaml          # Primary config (credentials, provider settings, user prefs)
  .env                 # Auto-generated bridge for settings.py backward compat
  portfolios/
    default.yaml       # Generated portfolio config (mirrors config/portfolio.yaml structure)
  risk_profiles/
    default.yaml       # Risk limits (mirrors config/risk_limits.yaml structure)
  normalizers/         # Already exists at ~/.risk_module/normalizers/ — migrate path
  cache/               # FMP cache, provider cache
```

### Config YAML schema

```yaml
# ~/.portfolio-mcp/config.yaml
version: 1

# User identity (replaces RISK_MODULE_USER_EMAIL)
user:
  email: "user@example.com"

# Market data provider
fmp:
  api_key: "abc123..."
  # cache_dir: ~/.portfolio-mcp/cache/fmp  (default)

# Brokerage connections (all optional)
brokers:
  ibkr:
    enabled: false
    # gateway:
    #   host: "127.0.0.1"
    #   port: 4002
    #   client_id: 1
    #   timeout: 10
    #   readonly: true
    # flex:
    #   token: "..."
    #   query_id: "..."
  schwab:
    enabled: false
    # app_key: "..."
    # app_secret: "..."
    # callback_url: "https://127.0.0.1"
  plaid:
    enabled: false
    # client_id: "..."
    # secret: "..."
    # env: "sandbox"
  snaptrade:
    enabled: false
    # client_id: "..."
    # consumer_key: "..."

# Database (optional — omit for no-DB mode)
# database:
#   url: "postgresql://user:pass@localhost:5432/portfolio_db"

# Portfolio defaults
portfolio:
  base_currency: "USD"
  name: "My Portfolio"
  risk_profile: "default"        # references risk_profiles/default.yaml
  start_date: null               # null = dynamic (today - 7 years)
  normalize_weights: false

# Analysis defaults
analysis:
  benchmark: "SPY"
  worst_case_lookback_years: 10
  expected_returns_lookback_years: 10
```

### Module structure

```
cli/
  __init__.py
  setup.py          # Main wizard entry point
  config.py         # Config loading/saving, schema, migration
  validators.py     # API key validation, connectivity tests
  prompts.py        # Interactive prompt helpers (wraps questionary)
  env_bridge.py     # Generate .env from config.yaml for backward compat
  detect.py         # First-run detection, provider tier detection
```

### Entry point

```
# After pip install portfolio-mcp:
portfolio-mcp setup           # Full wizard
portfolio-mcp setup --fmp     # Just FMP key setup
portfolio-mcp setup --broker  # Just brokerage setup
portfolio-mcp setup --check   # Validate existing config (non-interactive)
portfolio-mcp setup --reset   # Reset to defaults (with confirmation)
```

---

## Implementation Steps

### Step 1: Config module (`cli/config.py`)

**Goal**: Config loading, saving, schema validation, migration logic.

**Files to create**:
- `cli/__init__.py`
- `cli/config.py`

**Scope**:
- `get_config_home() -> Path` — resolve config directory (XDG-aware)
- `load_config() -> dict` — load `config.yaml`, return empty dict if missing
- `save_config(config: dict) -> Path` — write `config.yaml` with atomic write (write to tmp + rename)
- `get_config_value(key_path: str, default=None)` — dot-path accessor (`"fmp.api_key"`)
- `set_config_value(key_path: str, value)` — dot-path setter
- `CONFIG_SCHEMA` — version, required fields, type hints for validation
- `migrate_config(config: dict) -> dict` — version migration (v1 -> v2 when schema changes)
- `is_first_run() -> bool` — True when `config.yaml` does not exist

**Key constraint**: Config module must be importable without heavy dependencies (no FastMCP, no pandas). It will be used both by the wizard CLI and by `mcp_server.py` at boot.

**Tests**: 12-15 tests
- Load/save round-trip
- Missing file returns empty dict
- Atomic write (crash safety)
- Dot-path get/set
- Schema migration
- XDG_CONFIG_HOME respected on Linux
- `is_first_run()` before and after config creation

---

### Step 2: Validators (`cli/validators.py`)

**Goal**: Validate API keys and connectivity before saving to config.

**Files to create**:
- `cli/validators.py`

**Scope**:
- `validate_fmp_key(api_key: str) -> tuple[bool, str]` — hit FMP `/api/v3/profile/AAPL` with the key; return (success, message). Handles 401 (invalid key), 429 (rate limited but valid), timeout, network error.
- `validate_ibkr_gateway(host: str, port: int) -> tuple[bool, str]` — TCP connect to gateway, return (reachable, message). Does NOT require full IB auth — just port reachability.
- `validate_ibkr_flex(token: str, query_id: str) -> tuple[bool, str]` — attempt a Flex query initiation; return (success, message).
- `validate_database_url(url: str) -> tuple[bool, str]` — psycopg2 connect + `SELECT 1`, return (success, message). Catches auth errors separately from connectivity errors.
- `validate_plaid_credentials(client_id: str, secret: str, env: str) -> tuple[bool, str]` — hit Plaid `/institutions/get` with credentials.
- `check_provider_status() -> dict[str, dict]` — check all configured providers, return status map.

**Key constraint**: Each validator must have a short timeout (5s default) and must never crash — always return `(False, "reason")`.

**Tests**: 10-12 tests
- FMP valid key (mock 200 response)
- FMP invalid key (mock 401)
- FMP network error (mock timeout)
- IBKR gateway reachable / unreachable
- Database URL valid / invalid / missing psycopg2
- `check_provider_status()` with mixed availability

---

### Step 3: Interactive prompts (`cli/prompts.py`)

**Goal**: Reusable prompt helpers for the wizard, wrapping `questionary` (or fallback to `input()` if not installed).

**Files to create**:
- `cli/prompts.py`

**Scope**:
- `ask_text(message, default=None, secret=False) -> str` — text input with optional masking for API keys
- `ask_choice(message, choices, default=None) -> str` — single-select list
- `ask_confirm(message, default=True) -> bool` — yes/no
- `print_status(provider, ok, message)` — formatted status line (checkmark/cross + provider name + message)
- `print_header(text)` — section header formatting
- `print_summary(config)` — formatted summary of what was configured
- Graceful fallback to `input()` / `getpass()` when `questionary` is not installed (CI environments, minimal installs)

**Dependency**: `questionary` (optional). Add to `extras_require` in setup, not hard requirement.

**Tests**: 5-6 tests
- Fallback mode works without questionary
- `print_status` formatting
- `print_summary` with partial config

---

### Step 4: Env bridge (`cli/env_bridge.py`)

**Goal**: Generate a `.env` file from `config.yaml` for backward compatibility with `settings.py` and MCP server boot.

**Files to create**:
- `cli/env_bridge.py`

**Scope**:
- `generate_env_file(config: dict, output_path: Path) -> Path` — map config YAML keys to env var names and write `.env`
- Mapping table:

| Config YAML path | Env var |
|---|---|
| `user.email` | `RISK_MODULE_USER_EMAIL` |
| `fmp.api_key` | `FMP_API_KEY` |
| `brokers.ibkr.enabled` | `IBKR_ENABLED` |
| `brokers.ibkr.gateway.host` | `IBKR_GATEWAY_HOST` |
| `brokers.ibkr.gateway.port` | `IBKR_GATEWAY_PORT` |
| `brokers.ibkr.gateway.client_id` | `IBKR_CLIENT_ID` |
| `brokers.ibkr.gateway.timeout` | `IBKR_TIMEOUT` |
| `brokers.ibkr.gateway.readonly` | `IBKR_READONLY` |
| `brokers.ibkr.flex.token` | `IBKR_FLEX_TOKEN` |
| `brokers.ibkr.flex.query_id` | `IBKR_FLEX_QUERY_ID` |
| `brokers.schwab.enabled` | `SCHWAB_ENABLED` |
| `brokers.schwab.app_key` | `SCHWAB_APP_KEY` |
| `brokers.schwab.app_secret` | `SCHWAB_APP_SECRET` |
| `brokers.plaid.client_id` | `PLAID_CLIENT_ID` |
| `brokers.plaid.secret` | `PLAID_SECRET` |
| `brokers.plaid.env` | `PLAID_ENV` |
| `brokers.snaptrade.client_id` | `SNAPTRADE_CLIENT_ID` |
| `brokers.snaptrade.consumer_key` | `SNAPTRADE_CONSUMER_KEY` |
| `database.url` | `DATABASE_URL` |

- The `.env` file includes a header comment: `# Auto-generated by portfolio-mcp setup. Edit config.yaml instead.`
- Only writes keys that have non-empty values (avoids `FMP_API_KEY=` lines that override real env vars with empty strings).

**Tests**: 6-8 tests
- Full config produces correct .env
- Partial config omits unset keys
- Secrets not double-quoted
- Header comment present
- Round-trip: generate .env, load with dotenv, values match

---

### Step 5: Provider detection (`cli/detect.py`)

**Goal**: Detect what tier/capabilities the user has based on configured keys, and detect first-run state.

**Files to create**:
- `cli/detect.py`

**Scope**:
- `detect_tier(config: dict) -> str` — returns `"free"`, `"pro"`, or `"enterprise"` based on configured providers
- `detect_configured_providers(config: dict) -> list[str]` — list of provider names with credentials present
- `detect_available_features(config: dict) -> dict[str, bool]` — feature availability map:
  ```python
  {
      "market_data": True,           # FMP key present
      "live_positions": False,       # IBKR/Schwab/aggregator not configured
      "trade_history": False,        # IBKR Flex/Schwab not configured
      "realized_performance": False, # Needs trade history
      "trading": False,              # Needs IBKR Gateway + IBKR_ENABLED
      "multi_institution": False,    # Needs Plaid or SnapTrade
      "persistent_storage": False,   # No DATABASE_URL
  }
  ```
- `needs_setup() -> bool` — True when config is missing or FMP key is not set (minimum viable config)
- `get_setup_recommendations(config: dict) -> list[str]` — ordered list of "next steps" based on current config gaps

**Tests**: 8-10 tests
- Free tier detection (FMP only)
- Pro tier detection (FMP + IBKR)
- Enterprise tier detection (FMP + Plaid)
- Feature map with various configs
- `needs_setup()` before and after config
- Recommendations for empty config vs partial config

---

### Step 6: Main wizard (`cli/setup.py`)

**Goal**: The interactive wizard that walks users through configuration.

**Files to create**:
- `cli/setup.py`

**Scope — Wizard flow**:

```
$ portfolio-mcp setup

Welcome to portfolio-mcp setup.

Step 1/4: User Identity
  Email address (used for portfolio lookups): [user@example.com]

Step 2/4: Market Data
  FMP (Financial Modeling Prep) provides market data, fundamentals, and news.
  Get a free API key at: https://financialmodelingprep.com/developer/docs

  FMP API key: [********]
  Validating... OK (plan: starter, calls remaining: 248/250)

Step 3/4: Brokerage Connection (optional)
  Connect a brokerage for live positions and trade history.
  > [1] Interactive Brokers (API Gateway + Flex)
    [2] Schwab (OAuth)
    [3] Skip — I'll import via CSV

  [If IBKR selected:]
  IB Gateway host [127.0.0.1]:
  IB Gateway port [4002]:
  Testing connection... OK (connected, paper account)

  IBKR Flex token (for trade history): [********]
  IBKR Flex query ID: [********]

Step 4/4: Portfolio Settings
  Base currency [USD]:
  Portfolio name [My Portfolio]:
  Benchmark ticker [SPY]:

  Do you have a CSV file to import? [y/N]:
  [If yes:] Path to CSV: ~/exports/schwab_positions.csv

Summary:
  Config:     ~/.portfolio-mcp/config.yaml
  Market data: FMP (validated)
  Brokerage:  Interactive Brokers (Gateway + Flex)
  Database:   None (no-DB mode — analysis works, persistence requires PostgreSQL)
  Tier:       Pro (live positions, trade history, full analysis)

  Features available:
    [x] Market data and fundamentals
    [x] Risk scoring and factor analysis
    [x] Live positions (IBKR)
    [x] Trade history and realized P&L (IBKR Flex)
    [ ] Multi-institution aggregation (add Plaid or SnapTrade)
    [ ] Persistent storage (set DATABASE_URL)

  Next: Start the MCP server with 'portfolio-mcp serve'
        Or add to Claude Code: 'claude mcp add portfolio-mcp -- portfolio-mcp serve'
```

**Subsection entry points**:
- `portfolio-mcp setup --fmp` — jump to Step 2 only
- `portfolio-mcp setup --broker` — jump to Step 3 only
- `portfolio-mcp setup --portfolio` — jump to Step 4 only
- `portfolio-mcp setup --check` — non-interactive validation of existing config

**CSV import integration**:
If the user provides a CSV path in Step 4, the wizard:
1. Reads the first 20 lines
2. Runs `detect_and_normalize()` from `inputs/normalizers.py`
3. If auto-detected, shows preview + confirms
4. If not detected, offers the normalizer builder flow (`normalizer_sample_csv` -> `normalizer_stage` -> `normalizer_test` -> `normalizer_activate`)
5. Writes the resulting portfolio to `~/.portfolio-mcp/portfolios/default.yaml` in the `config/portfolio.yaml` format

**Key behaviors**:
- Pre-fills from existing `config.yaml` when re-running
- Ctrl+C at any point saves nothing (atomic — all-or-nothing write at end)
- `--non-interactive` mode reads from env vars / existing config only (for CI/Docker)
- Sensitive values (API keys) are masked in terminal and in `print_summary()`

**Tests**: 15-20 tests
- Full wizard flow (mock prompts)
- Re-run with existing config pre-fills values
- Ctrl+C produces no partial config
- `--check` mode with valid config
- `--check` mode with invalid/missing config
- `--fmp` subsection only writes FMP config
- CSV import detection + portfolio generation
- `--non-interactive` reads from env vars
- Summary output formatting

---

### Step 7: MCP server integration

**Goal**: Wire the config system into MCP server startup so the server reads from `~/.portfolio-mcp/config.yaml` and shows actionable guidance when config is missing.

**Files to modify**:
- `mcp_server.py`
- `settings.py`

**Scope**:

1. **Config loading in `settings.py`**: Add a new resolution layer. Current chain is `env var -> dotenv -> hardcoded default`. New chain: `env var -> dotenv -> user config YAML -> hardcoded default`.

```python
# In settings.py, add after dotenv loading:
def _load_user_config() -> dict:
    """Load user config from ~/.portfolio-mcp/config.yaml if it exists."""
    try:
        from cli.config import load_config
        return load_config()
    except Exception:
        return {}

_USER_CONFIG = _load_user_config()
```

Then in `_read_env_or_dotenv`, add a third fallback layer that checks `_USER_CONFIG` before returning the hardcoded default.

2. **First-run detection in `mcp_server.py`**: Replace current `_validate_environment()` with a richer check:

```python
def _validate_environment() -> bool:
    from cli.detect import needs_setup, get_setup_recommendations

    if needs_setup():
        print("No configuration found. Run 'portfolio-mcp setup' to configure.", file=sys.stderr)
        print("Or set FMP_API_KEY and RISK_MODULE_USER_EMAIL environment variables.", file=sys.stderr)
        # Don't abort — allow server to start in degraded mode

    # ... existing validation logic with improved messages ...
```

3. **Env bridge auto-generation**: When the wizard writes `config.yaml`, it also writes `~/.portfolio-mcp/.env`. The `settings.py` dotenv loader can optionally load this file as a secondary dotenv source (lower priority than project-root `.env`).

**Key constraint**: The MCP server must still work without the wizard. Users who set env vars directly (Docker, CI, existing workflows) are not broken. The config YAML is an additional resolution layer, not a replacement.

**Tests**: 8-10 tests
- Server boots with config.yaml only (no env vars, no .env)
- Server boots with env vars only (no config.yaml)
- Env vars take precedence over config.yaml
- Project .env takes precedence over user config.yaml
- `needs_setup()` shown when no config exists
- Degraded mode still starts server

---

### Step 8: Portfolio YAML generation

**Goal**: Generate a portfolio config file from CSV import or manual entry during wizard.

**Files to create**:
- `cli/portfolio_gen.py`

**Scope**:
- `generate_portfolio_yaml(positions: list[dict], name: str, currency: str) -> dict` — convert normalized positions into `config/portfolio.yaml` format (with `portfolio_input`, `expected_returns`, `stock_factor_proxies` sections)
- `generate_risk_profile_yaml(risk_level: int) -> dict` — generate risk limits based on selected risk level (1-5 scale mapped to conservative/moderate/aggressive profiles)
- Risk level mapping:

| Level | Label | max_volatility | max_loss | max_single_stock |
|---|---|---|---|---|
| 1 | Conservative | 0.15 | -0.10 | 0.20 |
| 2 | Moderate-Conservative | 0.25 | -0.15 | 0.30 |
| 3 | Moderate | 0.35 | -0.20 | 0.35 |
| 4 | Moderate-Aggressive | 0.40 | -0.25 | 0.40 |
| 5 | Aggressive | 0.50 | -0.35 | 0.50 |

- Write to `~/.portfolio-mcp/portfolios/default.yaml` and `~/.portfolio-mcp/risk_profiles/default.yaml`
- For positions without factor proxies, the wizard defers proxy generation to runtime (the analysis engine resolves proxies dynamically when not specified in YAML)

**Tests**: 6-8 tests
- CSV positions to portfolio YAML round-trip
- Risk level mapping for each level
- Empty positions list produces valid skeleton
- Factor proxies omitted when not available

---

### Step 9: CLI entry point + packaging

**Goal**: Wire the wizard into a `portfolio-mcp` CLI command.

**Files to modify**:
- `pyproject.toml` or `setup.cfg` (entry point registration)
- `cli/__init__.py`

**Scope**:
- Register `portfolio-mcp` as a console entry point (or `python -m cli.setup` as alternative)
- Subcommands:
  - `portfolio-mcp setup` — full wizard (Steps 1-4)
  - `portfolio-mcp setup --check` — non-interactive config validation
  - `portfolio-mcp setup --fmp` / `--broker` / `--portfolio` — targeted subsections
  - `portfolio-mcp setup --non-interactive` — read from env vars, validate, write config
  - `portfolio-mcp setup --reset` — delete config and re-run wizard
  - `portfolio-mcp serve` — start MCP server (alias for current `python mcp_server.py`)
  - `portfolio-mcp status` — show current config summary, provider status, feature availability
- Use `click` for CLI framework (already a transitive dependency via several packages; lightweight, well-tested)
- `--help` for each subcommand

**Tests**: 5-6 tests
- `setup --check` exit codes (0 = valid, 1 = invalid)
- `status` output with various configs
- `--non-interactive` reads env vars correctly
- `--reset` with confirmation

---

### Step 10: Documentation and .env.example update

**Goal**: Update docs to reference the wizard as the primary setup path.

**Files to modify**:
- `docs/reference/ENVIRONMENT_SETUP.md` — add wizard section at top, keep manual setup as alternative
- `.env.example` — add comment pointing to wizard
- `README.md` — quick start references wizard

**Scope**:
- `ENVIRONMENT_SETUP.md`: New "Quick Start (recommended)" section at top:
  ```
  ## Quick Start (recommended)

  pip install portfolio-mcp
  portfolio-mcp setup
  ```
  Existing manual setup section remains below as "Manual Configuration (advanced)".

- `.env.example`: Add header:
  ```
  # TIP: Run 'portfolio-mcp setup' for guided configuration.
  # This file is for manual/advanced setup. The wizard generates config
  # at ~/.portfolio-mcp/config.yaml which is loaded automatically.
  ```

---

## Integration Points

### How settings.py resolution changes

Current resolution order (per variable):
1. `os.getenv(KEY)` — runtime environment
2. `_read_key_from_env_file(.env, KEY)` — project `.env` file
3. Hardcoded default

New resolution order:
1. `os.getenv(KEY)` — runtime environment (unchanged)
2. `_read_key_from_env_file(.env, KEY)` — project `.env` file (unchanged)
3. **User config YAML** — `~/.portfolio-mcp/config.yaml` mapped via env bridge
4. Hardcoded default (unchanged)

Implementation: The env bridge generates `~/.portfolio-mcp/.env` from `config.yaml`. We add this as a secondary dotenv source in `settings.py` after the project `.env`:

```python
# settings.py — after existing load_dotenv
_user_env_path = Path.home() / ".portfolio-mcp" / ".env"
if _user_env_path.exists():
    load_dotenv(_user_env_path, override=False)  # override=False: project .env wins
```

This is the minimal-change integration path. The existing `_read_env_or_dotenv()` and `os.getenv()` calls throughout the codebase continue to work unchanged.

### How mcp_server.py boot changes

The existing `_validate_environment()` function gains an additional check at the top:

```python
from cli.detect import needs_setup

if needs_setup():
    print("No configuration found. Run 'portfolio-mcp setup' to get started.", file=sys.stderr)
```

The server still boots (no hard abort). This is a guidance message, not a gate.

### How `providers/routing.py` stays unchanged

The provider routing system reads from env vars exclusively (`is_provider_enabled()`, `is_provider_available()`). The env bridge ensures that wizard-configured credentials are present as env vars at runtime. No changes needed to `routing.py`.

### Normalizer directory migration

The normalizer builder currently uses `~/.risk_module/normalizers/`. The wizard should symlink or copy this to `~/.portfolio-mcp/normalizers/` if the old path exists, and update `_DIRS` in `normalizer_builder.py` to check the new path first with fallback to the old path.

---

## Testing Strategy

### Unit tests (Steps 1-6, 8)

Each module gets its own test file in `tests/cli/`:

| Test file | Coverage |
|---|---|
| `test_config.py` | Load, save, migrate, dot-path access, first-run detection |
| `test_validators.py` | FMP key validation (mocked HTTP), IBKR probe (mocked socket), DB connect (mocked psycopg2) |
| `test_prompts.py` | Fallback mode, formatting |
| `test_env_bridge.py` | YAML-to-.env mapping, round-trip, partial config |
| `test_detect.py` | Tier detection, feature availability, needs_setup |
| `test_setup.py` | Wizard flow with mocked prompts, subsection entry, pre-fill |
| `test_portfolio_gen.py` | CSV-to-YAML conversion, risk profile generation |

**Estimated total**: 70-85 tests

### Integration tests (Steps 7, 9)

| Test | What it validates |
|---|---|
| Server boot with config.yaml only | `settings.py` loads user config as secondary dotenv |
| Server boot with env vars + config.yaml | Env vars take precedence |
| `portfolio-mcp setup --check` exit codes | CLI entry point works |
| `portfolio-mcp status` with running server | Status report includes provider health |

### Manual testing checklist

- [ ] Fresh install: `pip install portfolio-mcp && portfolio-mcp setup` — complete flow
- [ ] Re-run: `portfolio-mcp setup` with existing config pre-fills correctly
- [ ] Subsection: `portfolio-mcp setup --fmp` only touches FMP config
- [ ] Invalid FMP key: wizard rejects and re-prompts
- [ ] CSV import: provide a Schwab CSV, see normalized positions, confirm portfolio generation
- [ ] MCP server start: `portfolio-mcp serve` reads wizard config, tools work
- [ ] Claude Code integration: `claude mcp add portfolio-mcp -- portfolio-mcp serve` and tools respond
- [ ] No-DB mode: all analysis tools work without DATABASE_URL
- [ ] `Ctrl+C` during wizard: no partial config written

---

## Dependencies

| Dependency | Required | Notes |
|---|---|---|
| `click` | Yes | CLI framework. Already transitive dependency. |
| `pyyaml` | Yes | Already a direct dependency (13 YAML configs). |
| `questionary` | Optional | Rich terminal prompts. Falls back to `input()`. Add to `extras_require["wizard"]`. |
| `requests` | Yes | Already a direct dependency. Used for FMP key validation. |

No new heavy dependencies. The wizard module adds ~500 lines of code across 7 files.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Config YAML schema changes break existing users | Users must re-run wizard | `version` field + `migrate_config()` handles schema evolution |
| Env bridge .env conflicts with project .env | Wrong values loaded | `override=False` ensures project .env always wins; user .env is lowest priority |
| FMP validation endpoint changes or is rate-limited | Wizard fails on valid key | Use profile endpoint (stable, low-cost); handle 429 as "valid but rate-limited" |
| User has both old `~/.risk_module/` and new `~/.portfolio-mcp/` | Normalizer confusion | Check old path, offer migration, symlink for backward compat |
| `questionary` not installed in minimal environment | Wizard unusable | Fallback to `input()` / `getpass()` built into `prompts.py` |

---

## Estimated Effort

| Step | Effort | Lines (est.) |
|---|---|---|
| 1. Config module | Small | ~120 |
| 2. Validators | Small | ~150 |
| 3. Prompts | Small | ~80 |
| 4. Env bridge | Small | ~60 |
| 5. Provider detection | Small | ~100 |
| 6. Main wizard | Medium | ~250 |
| 7. MCP server integration | Small | ~40 (changes to existing files) |
| 8. Portfolio YAML generation | Small | ~100 |
| 9. CLI entry point | Small | ~60 |
| 10. Documentation | Small | ~30 (doc edits) |
| **Total** | **Medium** | **~990 code + ~85 tests** |

Estimated calendar time: 2-3 sessions.

---

## Open Questions

1. **Package name**: `portfolio-mcp` or `openclaw`? The config directory and CLI name depend on this. Plan uses `portfolio-mcp` as a placeholder; easy to rename via a single constant.

2. **Managed FMP key**: The strategy doc mentions a "use our managed key for $X/month" option in the wizard. Implementing this requires a key provisioning API on our side. Defer to post-launch? The wizard can show the option as "coming soon" initially.

3. **SQLite for persistence**: The strategy doc mentions "SQLite for simple, Postgres for full." The current no-DB mode has no SQLite path. Adding SQLite as an intermediate tier between no-DB and Postgres is a separate feature (not in this plan's scope, but the config schema reserves a `database` section for it).

4. **AI model configuration**: The strategy doc shows a Step 3 for AI model selection (Anthropic/OpenAI/local). This is gated on C1 (Agent Gateway Abstraction) and C3 (Agent Extraction), which are not yet built. The wizard reserves a `model` section in the config schema but does not prompt for it until those features exist.

---

*This plan implements item C2 from `docs/OPEN_SOURCE_LAUNCH_GAPS.md`. It can be started before B4 (portfolio-mcp extraction) is complete — the CLI module works with the current codebase and will be carried forward during extraction.*
