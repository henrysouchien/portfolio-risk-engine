# Docker Compose Self-Hosting Plan

> **Status**: NOT STARTED
> **Created**: 2026-03-19
> **ID**: B2
> **Parent**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_GAPS.md` (Phase B)
> **Depends on**: None (can be built independently)
> **Goal**: `git clone` + `cp .env.example .env` + `docker compose up` = working full-stack app

---

## Context

The platform currently runs as a set of loose processes started manually: a FastAPI backend (`uvicorn app:app`), a Vite dev server or static build for the frontend, and a PostgreSQL database. There is no containerization, no orchestration, and no single-command path from clone to running app. Self-hosters must install Python 3.11+, Node 22+, pnpm, PostgreSQL, and configure everything by hand.

Docker Compose brings the entire stack to a single `docker compose up`. This is table-stakes for open-source adoption and a prerequisite for the hosted deployment story.

---

## Architecture Overview

```
docker compose up
  |
  +--> postgres      (port 5432 internal)
  |      schema.sql + migrations on first run
  |
  +--> redis         (port 6379 internal, optional)
  |      L2 cache for cross-worker sharing
  |
  +--> backend       (port 5001 internal, exposed 5001)
  |      FastAPI + uvicorn, waits for postgres healthy
  |      Mounts config/ YAMLs read-only
  |
  +--> frontend      (port 80 internal, exposed 3000)
         Vite build -> nginx serve
         Proxies /api, /auth, /plaid -> backend:5001
```

### What is NOT containerized

MCP servers (`mcp_server.py`, `fmp/server.py`, `ibkr_mcp_server.py`) are **stdio-based processes spawned by Claude Code**. They run on the developer's machine, not inside containers. Docker Compose covers the web application stack only. MCP servers continue to run locally per `docs/reference/MCP_SERVERS.md`.

IBKR Gateway (IB Gateway / TWS) runs as a separate desktop application or headless container managed by the user. We document how to point `IBKR_GATEWAY_HOST` at it but do not include it in compose.

---

## Step-by-Step Implementation

### Step 1: Backend Dockerfile

**File**: `docker/backend/Dockerfile`

```dockerfile
FROM python:3.11-slim AS base

# System deps for psycopg2-binary, scipy, cvxpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/health')" || exit 1

# Run with uvicorn (4 workers, no reload in production)
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "4"]
```

**Key decisions**:
- `python:3.11-slim` as base. The project requires `>=3.11` per `app_platform/pyproject.toml`. Slim variant keeps image size down.
- System packages `gcc g++ libpq-dev` needed for `psycopg2-binary` and numerical libs (`scipy`, `cvxpy`). These could move to a multi-stage build later to shrink the final image.
- 4 workers matches the `Makefile` default (`UVICORN_WORKERS ?= 4`).
- No `--reload` in production. Dev profile overrides this (see Step 7).

**Files to copy** (the `COPY . .` copies the full backend):
- `app.py`, `settings.py`, `mcp_server.py` (entry points)
- `core/`, `portfolio_risk_engine/`, `providers/`, `services/`, `trading_analysis/`, `utils/`, `mcp_tools/`, `inputs/`, `routes/`, `models/`, `database/`, `fmp/`, `ibkr/`, `app_platform/`, `config/`

**`.dockerignore`** (Step 5) ensures `frontend/`, `node_modules/`, `.git/`, `docs/`, `tests/`, `__pycache__/`, `.env` are excluded.

**Open question**: Multi-stage build to strip gcc/g++ from final image. Deferred to a follow-up optimization pass — correctness first.

---

### Step 2: Frontend Dockerfile

**File**: `docker/frontend/Dockerfile`

```dockerfile
# --- Build stage ---
FROM node:22-slim AS build

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Install deps (layer cached unless lockfile changes)
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/packages/app-platform/package.json packages/app-platform/package.json
COPY frontend/packages/chassis/package.json packages/chassis/package.json
COPY frontend/packages/connectors/package.json packages/connectors/package.json
COPY frontend/packages/ui/package.json packages/ui/package.json
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY frontend/ .
# Inject build-time env vars via ARG -> .env
ARG VITE_API_URL=/
ARG VITE_GOOGLE_CLIENT_ID=
ARG VITE_ENVIRONMENT=production
ARG VITE_CHAT_BACKEND=gateway
RUN echo "VITE_API_URL=${VITE_API_URL}" > .env && \
    echo "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}" >> .env && \
    echo "VITE_ENVIRONMENT=${VITE_ENVIRONMENT}" >> .env && \
    echo "VITE_CHAT_BACKEND=${VITE_CHAT_BACKEND}" >> .env
RUN pnpm build

# --- Serve stage ---
FROM nginx:alpine

# Custom nginx config
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1
```

**Key decisions**:
- Two-stage build: Node for `pnpm build`, then nginx:alpine to serve static files. Final image is tiny (~30MB).
- `VITE_API_URL=/` means the frontend makes relative API requests (`/api/...`). nginx proxies these to the backend container. This avoids CORS and hardcoded URLs.
- `pnpm-workspace.yaml` + per-package `package.json` files copied first for layer caching.
- `pnpm install --frozen-lockfile` ensures reproducible builds.
- Build output goes to `frontend/build/` per `vite.config.ts` (`outDir: 'build'`).

---

### Step 3: nginx Configuration

**File**: `docker/frontend/nginx.conf`

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # API proxy to backend
    location /api/ {
        proxy_pass http://backend:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;  # Long-running analysis endpoints
    }

    location /auth/ {
        proxy_pass http://backend:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /plaid/ {
        proxy_pass http://backend:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /admin/ {
        proxy_pass http://backend:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE streaming for chat (long-lived connections)
    location /claude/ {
        proxy_pass http://backend:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;  # Long SSE streams
    }

    # SPA fallback: all other routes serve index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Gzip static assets
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    gzip_min_length 256;
}
```

**Key decisions**:
- Proxies `/api/`, `/auth/`, `/plaid/`, `/admin/`, `/claude/` to `backend:5001` (Docker internal DNS).
- Mirrors the Vite dev server proxy config from `vite.config.ts` (`/api`, `/auth`, `/plaid`), plus `/admin/` and `/claude/` for completeness.
- SSE location (`/claude/`) disables buffering and extends timeout for streaming chat.
- SPA fallback (`try_files $uri $uri/ /index.html`) for client-side routing.
- 120s read timeout on `/api/` for long-running analysis (factor decomposition, Monte Carlo can take 30-60s).

---

### Step 4: Database Initialization

**File**: `docker/postgres/init.sh`

```bash
#!/bin/bash
set -e

# This script runs once when the postgres container data volume is empty.
# It creates the database and applies schema + migrations.

echo "=== Initializing risk_module database ==="

# Apply base schema
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -f /docker-entrypoint-initdb.d/schema.sql

# Apply migrations in order
MIGRATION_DIR="/docker-entrypoint-initdb.d/migrations"
if [ -d "$MIGRATION_DIR" ]; then
    for migration in $(ls "$MIGRATION_DIR"/*.sql | sort); do
        echo "Applying migration: $(basename $migration)"
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
            -f "$migration"
    done
fi

echo "=== Database initialization complete ==="
```

**How it works**:
- PostgreSQL's official Docker image runs all scripts in `/docker-entrypoint-initdb.d/` on first start (when the data volume is empty).
- `schema.sql` creates all tables, indexes, triggers, and seed data. It already includes `DROP IF EXISTS` guards.
- Migrations from `database/migrations/` are applied in alphabetical order after the base schema.
- The `ON_ERROR_STOP=1` flag ensures any migration failure halts the process (fail-fast).

**Volume mount strategy**:
- `database/schema.sql` -> `/docker-entrypoint-initdb.d/schema.sql`
- `database/migrations/` -> `/docker-entrypoint-initdb.d/migrations/`
- `docker/postgres/init.sh` -> `/docker-entrypoint-initdb.d/00-init.sh` (runs first via alphabetical ordering)

**Sample data handling**: `schema.sql` currently includes sample data inserts (user `hc@henrychien.com`, sample portfolio). For the open-source release, these should be either:
1. Removed from `schema.sql` and placed in a separate `seed_sample_data.sql` (preferred)
2. Gated behind an environment variable

This is a release-scrub item (C4), not blocking for Docker Compose.

---

### Step 5: docker-compose.yml

**File**: `docker-compose.yml` (project root)

```yaml
# Portfolio Risk Analysis Platform — Docker Compose
# Quick start: cp .env.example .env && edit .env && docker compose up

services:
  # ---------- PostgreSQL ----------
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-risk_module_db}
      POSTGRES_USER: ${POSTGRES_USER:-risk_module}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres/init.sh:/docker-entrypoint-initdb.d/00-init.sh:ro
      - ./database/schema.sql:/docker-entrypoint-initdb.d/schema.sql:ro
      - ./database/migrations:/docker-entrypoint-initdb.d/migrations:ro
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-risk_module} -d ${POSTGRES_DB:-risk_module_db}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s

  # ---------- Redis (optional L2 cache) ----------
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "${REDIS_PORT:-6379}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    profiles:
      - full
      - with-redis

  # ---------- FastAPI Backend ----------
  backend:
    build:
      context: .
      dockerfile: docker/backend/Dockerfile
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      # Database (constructed from compose variables)
      DATABASE_URL: postgresql://${POSTGRES_USER:-risk_module}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-risk_module_db}
      DB_POOL_MIN: ${DB_POOL_MIN:-2}
      DB_POOL_MAX: ${DB_POOL_MAX:-10}
      USE_DATABASE: "true"

      # External API keys (passed through from .env)
      FMP_API_KEY: ${FMP_API_KEY:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}

      # Auth
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}
      GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET:-}
      FLASK_SECRET_KEY: ${FLASK_SECRET_KEY:?Set FLASK_SECRET_KEY in .env}
      ADMIN_TOKEN: ${ADMIN_TOKEN:-}

      # Brokerage integrations (optional)
      PLAID_CLIENT_ID: ${PLAID_CLIENT_ID:-}
      PLAID_SECRET: ${PLAID_SECRET:-}
      PLAID_ENV: ${PLAID_ENV:-sandbox}
      IBKR_ENABLED: ${IBKR_ENABLED:-false}
      IBKR_GATEWAY_HOST: ${IBKR_GATEWAY_HOST:-}
      IBKR_GATEWAY_PORT: ${IBKR_GATEWAY_PORT:-4002}
      IBKR_FLEX_TOKEN: ${IBKR_FLEX_TOKEN:-}
      IBKR_FLEX_QUERY_ID: ${IBKR_FLEX_QUERY_ID:-}

      # Gateway proxy (AI chat)
      GATEWAY_URL: ${GATEWAY_URL:-}
      GATEWAY_API_KEY: ${GATEWAY_API_KEY:-}
      GATEWAY_SSL_VERIFY: ${GATEWAY_SSL_VERIFY:-true}

      # Redis (when profile active)
      REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
      REDIS_CACHE_ENABLED: ${REDIS_CACHE_ENABLED:-false}

      # User context
      RISK_MODULE_USER_EMAIL: ${RISK_MODULE_USER_EMAIL:-}

      # URLs (internal Docker network)
      FRONTEND_BASE_URL: ${FRONTEND_BASE_URL:-http://localhost:3000}
      BACKEND_BASE_URL: http://backend:5001

      # Runtime
      ENVIRONMENT: ${ENVIRONMENT:-production}
    volumes:
      # Config YAMLs (read-only)
      - ./config:/app/config:ro
      # FMP price cache (persistent)
      - fmp_cache:/app/cache_prices
    ports:
      - "${BACKEND_PORT:-5001}:5001"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5001/health')"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3

  # ---------- Frontend (nginx + built React app) ----------
  frontend:
    build:
      context: .
      dockerfile: docker/frontend/Dockerfile
      args:
        VITE_API_URL: /
        VITE_GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}
        VITE_ENVIRONMENT: production
        VITE_CHAT_BACKEND: gateway
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy
    ports:
      - "${FRONTEND_PORT:-3000}:80"
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:80/"]
      interval: 30s
      timeout: 3s
      retries: 3

volumes:
  pgdata:
    driver: local
  fmp_cache:
    driver: local
```

**Key decisions**:

| Decision | Rationale |
|---|---|
| Redis behind `profiles: [full, with-redis]` | Not required for core functionality. `REDIS_CACHE_ENABLED` defaults to `false`. Self-hosters opt in with `docker compose --profile full up`. |
| `DATABASE_URL` constructed in compose | Users set `POSTGRES_PASSWORD` in `.env`, compose wires the full connection string. No need to manually construct `postgresql://...` URLs. |
| Config YAMLs as read-only volume mount | 12 YAML files in `config/` define factor proxies, risk limits, sector mappings, etc. Mounted `:ro` so the container reads them but does not modify. Self-hosters can edit these outside the container. |
| FMP cache as named volume | `fmp_cache` persists the Parquet price cache across container restarts. Without this, every restart re-fetches all price data from FMP API. |
| `FLASK_SECRET_KEY` and `POSTGRES_PASSWORD` required | The `?` syntax in `${VAR:?message}` makes compose fail with a clear error if these are unset. These are the two variables with no safe default. |
| Exposed ports configurable | `BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT` let self-hosters avoid port conflicts. |
| `restart: unless-stopped` | Survives host reboots. Does not restart if manually stopped. |

---

### Step 6: Environment Template for Docker

**File**: `.env.docker.example`

This is a Docker-specific env template. Separate from the existing `.env.example` (which targets local dev) because Docker Compose constructs `DATABASE_URL` internally and has different defaults.

```bash
# ============================================================================
# Docker Compose Environment Variables
# Copy to .env and fill in required values before running docker compose up
# ============================================================================

# ---------- REQUIRED ----------

# Database password (no default — you must set this)
POSTGRES_PASSWORD=change_me_to_a_secure_password

# Session encryption key (generate: python -c "import secrets; print(secrets.token_hex(32))")
FLASK_SECRET_KEY=

# ---------- STRONGLY RECOMMENDED ----------

# Financial Modeling Prep API key (required for market data, analysis, pricing)
# Get a free key at https://financialmodelingprep.com/developer/docs/
FMP_API_KEY=

# Google OAuth (required for web login)
# Create credentials at https://console.cloud.google.com/apis/credentials
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# ---------- OPTIONAL: AI Features ----------

# Anthropic API key (enables Claude-powered chat and analysis)
ANTHROPIC_API_KEY=

# OpenAI API key (alternative AI provider)
OPENAI_API_KEY=

# Gateway proxy (required for AI chat in the web app)
GATEWAY_URL=
GATEWAY_API_KEY=
GATEWAY_SSL_VERIFY=true

# ---------- OPTIONAL: Brokerage Connections ----------

# Plaid (live brokerage data from 10,000+ institutions)
PLAID_CLIENT_ID=
PLAID_SECRET=
PLAID_ENV=sandbox

# Interactive Brokers (requires IB Gateway running separately)
IBKR_ENABLED=false
IBKR_GATEWAY_HOST=host.docker.internal
IBKR_GATEWAY_PORT=4002
IBKR_FLEX_TOKEN=
IBKR_FLEX_QUERY_ID=

# ---------- OPTIONAL: Customization ----------

# Default user email for MCP tools
RISK_MODULE_USER_EMAIL=

# Admin API token
ADMIN_TOKEN=

# Database tuning
POSTGRES_DB=risk_module_db
POSTGRES_USER=risk_module
DB_POOL_MIN=2
DB_POOL_MAX=10

# Port overrides (change if defaults conflict)
FRONTEND_PORT=3000
BACKEND_PORT=5001
POSTGRES_PORT=5432

# Redis (enable for multi-worker cache sharing)
REDIS_CACHE_ENABLED=false
REDIS_PORT=6379

# Runtime environment
ENVIRONMENT=production
FRONTEND_BASE_URL=http://localhost:3000
```

**Note on IBKR_GATEWAY_HOST**: Set to `host.docker.internal` so the backend container can reach IB Gateway running on the Docker host. This works on Docker Desktop (macOS/Windows). On Linux, users need `--add-host=host.docker.internal:host-gateway` or the host's LAN IP.

---

### Step 7: Development Compose Override

**File**: `docker-compose.override.yml`

This file is automatically picked up by `docker compose up` when present. It overrides production settings for local development.

```yaml
# Development overrides — auto-loaded by docker compose up
# Delete or rename this file for production-like behavior

services:
  backend:
    build:
      context: .
      dockerfile: docker/backend/Dockerfile
    # Override CMD for hot reload (single worker)
    command: ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5001", "--reload"]
    volumes:
      # Mount source code for hot reload
      - .:/app
      - /app/__pycache__
      - /app/.venv
    environment:
      ENVIRONMENT: development

  frontend:
    # In dev, run Vite dev server instead of nginx
    build:
      context: .
      dockerfile: docker/frontend/Dockerfile.dev
    volumes:
      - ./frontend:/app
      - /app/node_modules
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    environment:
      - VITE_API_URL=http://localhost:5001
```

**File**: `docker/frontend/Dockerfile.dev`

```dockerfile
FROM node:22-slim
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/packages/app-platform/package.json packages/app-platform/package.json
COPY frontend/packages/chassis/package.json packages/chassis/package.json
COPY frontend/packages/connectors/package.json packages/connectors/package.json
COPY frontend/packages/ui/package.json packages/ui/package.json
RUN pnpm install
COPY frontend/ .
EXPOSE 3000
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
```

**Dev vs Prod behavior**:

| Aspect | Production | Development |
|---|---|---|
| Backend | 4 workers, no reload | 1 worker, `--reload`, source mounted |
| Frontend | nginx serving static build | Vite dev server with HMR |
| ENVIRONMENT | `production` | `development` |

**Profile usage**:
- `docker compose up` — dev mode (override file auto-loaded)
- `docker compose -f docker-compose.yml up` — production mode (skip override)
- `docker compose --profile full up` — includes Redis

---

### Step 8: .dockerignore

**File**: `.dockerignore`

```
# Version control
.git
.gitignore

# Frontend (separate Dockerfile)
frontend/node_modules

# Python
__pycache__
*.pyc
*.pyo
.venv
*.egg-info

# Environment (secrets)
.env
.env.local

# IDE
.vscode
.idea
*.swp

# Docs and tests (not needed in production image)
docs/
tests/
e2e/
*.md

# Build artifacts
frontend/build
frontend/coverage

# Cache files (mounted as volume instead)
cache_prices/

# Docker files (prevent recursive context)
docker-compose*.yml

# OS files
.DS_Store
Thumbs.db

# Dist repos (never ship these)
*-dist/
```

---

### Step 9: Health Check Endpoint

The backend needs a `/health` endpoint that Docker can probe. Check if one already exists.

**Investigation needed**: Search for an existing health check route in `app.py` or `routes/`.

If none exists, add a minimal one:

```python
@app.get("/health")
async def health_check():
    """Health check for Docker/load balancers."""
    checks = {"status": "ok"}
    # Optionally probe DB
    try:
        from database import is_db_available
        checks["database"] = "connected" if is_db_available() else "unavailable"
    except Exception:
        checks["database"] = "error"
    return checks
```

This should return 200 even when the database is down (the app supports no-DB mode). Docker health checks should pass as long as the process is responsive.

---

### Step 10: Quick Start Documentation

**File**: `docs/SELF_HOSTING.md` (or a section in the main README)

```markdown
## Self-Hosting with Docker Compose

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- An FMP API key (free at financialmodelingprep.com) for market data
- Google OAuth credentials (for web login) — optional for analysis-only mode

### Quick Start

1. Clone the repository
   git clone https://github.com/<org>/risk-module.git
   cd risk-module

2. Create your environment file
   cp .env.docker.example .env
   # Edit .env — at minimum set POSTGRES_PASSWORD and FLASK_SECRET_KEY

3. Start the stack
   docker compose up -d

4. Open the app
   http://localhost:3000

### What You Get

- Frontend dashboard at localhost:3000
- Backend API at localhost:5001 (OpenAPI docs at localhost:5001/docs)
- PostgreSQL at localhost:5432

### Configuration

All YAML config files in `config/` are mounted read-only into the backend
container. Edit them on your host and restart the backend:

  docker compose restart backend

### Including Redis

For multi-worker cache sharing:

  REDIS_CACHE_ENABLED=true docker compose --profile full up -d

### Stopping

  docker compose down           # stop containers, keep data
  docker compose down -v        # stop containers AND delete database volume

### Rebuilding After Code Changes

  docker compose build
  docker compose up -d

### Logs

  docker compose logs -f backend    # follow backend logs
  docker compose logs -f frontend   # follow frontend logs
  docker compose logs -f postgres   # follow database logs
```

---

## File Inventory

Files to create:

| File | Purpose |
|---|---|
| `docker/backend/Dockerfile` | Backend image (Python + deps + app code) |
| `docker/frontend/Dockerfile` | Frontend production image (Node build + nginx) |
| `docker/frontend/Dockerfile.dev` | Frontend dev image (Vite dev server) |
| `docker/frontend/nginx.conf` | nginx config (API proxy + SPA fallback) |
| `docker/postgres/init.sh` | Database initialization script |
| `docker-compose.yml` | Service orchestration (project root) |
| `docker-compose.override.yml` | Development overrides |
| `.dockerignore` | Build context exclusions |
| `.env.docker.example` | Docker-specific env template |
| `docs/SELF_HOSTING.md` | Quick start guide |

Files to modify:

| File | Change |
|---|---|
| `app.py` | Add `/health` endpoint (if not already present) |
| `.gitignore` | Add Docker-specific entries if missing |
| `docs/planning/launch/OPEN_SOURCE_LAUNCH_GAPS.md` | Update B2 status |

---

## Config and Volume Strategy

### YAML Config Files (read-only mount)

The 12 YAML files in `config/` are domain configuration, not secrets:

| File | Content |
|---|---|
| `portfolio.yaml` | Default portfolio definition |
| `risk_limits.yaml` | Default risk limit thresholds |
| `risk_limits_adjusted.yaml` | Adjusted risk limits |
| `asset_etf_proxies.yaml` | Asset class to ETF proxy mappings |
| `exchange_etf_proxies.yaml` | Exchange to factor proxy mappings |
| `exchange_mappings.yaml` | Exchange resolution rules |
| `industry_to_etf.yaml` | Industry to ETF mappings |
| `cash_map.yaml` | Cash identifier mappings |
| `sector_overrides.yaml` | Manual sector classification overrides |
| `security_type_mappings.yaml` | Security type classification rules |
| `strategy_templates.yaml` | Strategy builder templates |
| `what_if_portfolio.yaml` | What-if scenario templates |

These are mounted as `./config:/app/config:ro`. The `config/__init__.py` `resolve_config_path()` function already looks for these relative to the project root, so they resolve correctly inside the container at `/app/config/`.

### Persistent Volumes

| Volume | Purpose | Why persist |
|---|---|---|
| `pgdata` | PostgreSQL data directory | User data, portfolios, positions, sessions |
| `fmp_cache` | FMP Parquet price cache | Avoids re-fetching historical prices from FMP API on restart |

---

## MCP Server Considerations

MCP servers are **not** part of Docker Compose. They are stdio-based processes spawned by Claude Code on the developer's machine and communicate over stdin/stdout JSON-RPC.

However, self-hosters who want to use MCP tools with the Dockerized backend need to know:

1. **portfolio-mcp** (`mcp_server.py`): Needs `DATABASE_URL` pointing at the Docker Postgres. From the host, this is `postgresql://risk_module:<password>@localhost:5432/risk_module_db`. Add to `.env` for MCP usage.

2. **fmp-mcp** (`fmp/server.py`): Standalone, no database dependency. Works the same as before.

3. **ibkr-mcp** (`ibkr_mcp_server.py`): Standalone, talks to IB Gateway directly. No Docker interaction.

Document this in the self-hosting guide with example Claude Code registration commands that point at the Docker database.

---

## Testing Strategy

### Automated Tests

1. **Compose startup test**: `docker compose up -d && docker compose ps` — verify all services show "healthy".
2. **Schema initialization test**: `docker compose exec postgres psql -U risk_module -d risk_module_db -c "\dt"` — verify tables exist.
3. **API smoke test**: `curl http://localhost:5001/health` — verify backend responds.
4. **Frontend serve test**: `curl -s http://localhost:3000/ | grep "Portfolio Risk"` — verify HTML served.
5. **API proxy test**: `curl http://localhost:3000/api/health` — verify nginx proxies to backend.

### CI Integration

Add a GitHub Actions workflow (`.github/workflows/docker-compose-test.yml`):

```yaml
name: Docker Compose Test
on: [push, pull_request]
jobs:
  docker-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Create test .env
        run: |
          echo "POSTGRES_PASSWORD=test_password" > .env
          echo "FLASK_SECRET_KEY=test_secret_key_for_ci" >> .env
          echo "FMP_API_KEY=test" >> .env
      - name: Build and start
        run: docker compose -f docker-compose.yml up -d --build --wait
        timeout-minutes: 10
      - name: Check services healthy
        run: docker compose ps --format json | python -c "import sys,json; services=json.loads(sys.stdin.read()); assert all('healthy' in s.get('Health','') or s.get('State')=='running' for s in services)"
      - name: API health check
        run: curl -sf http://localhost:5001/health
      - name: Frontend check
        run: curl -sf http://localhost:3000/
      - name: Teardown
        if: always()
        run: docker compose down -v
```

### Manual QA Checklist

- [ ] `docker compose up` from clean clone with only required env vars
- [ ] Database tables created on first run
- [ ] Frontend loads at localhost:3000
- [ ] Backend API docs at localhost:5001/docs
- [ ] Google OAuth login flow works (requires valid OAuth credentials)
- [ ] CSV import works (free tier, no external API needed)
- [ ] Analysis endpoints return data when FMP key is configured
- [ ] `docker compose down && docker compose up` preserves database data
- [ ] `docker compose down -v && docker compose up` reinitializes database
- [ ] Port override works (`FRONTEND_PORT=8080 docker compose up`)
- [ ] Redis profile works (`docker compose --profile full up`)

---

## Migration Path

When deploying schema changes after initial setup, the Postgres init scripts only run on first start (empty volume). For subsequent migrations:

**Option A — Manual (sufficient for v1)**:
```bash
docker compose exec postgres psql -U risk_module -d risk_module_db \
    -f /docker-entrypoint-initdb.d/migrations/<new_migration>.sql
```

**Option B — Startup migration runner (future)**:
Add a migration runner to the backend entrypoint that checks applied migrations against a tracking table and applies new ones. This is a follow-up item, not required for initial Docker Compose support.

---

## Scope Boundaries

**In scope for this plan**:
- Dockerfiles for backend and frontend
- docker-compose.yml with all service definitions
- Database init automation
- nginx proxy configuration
- Environment variable management
- Dev vs prod profiles
- Quick start documentation
- Basic CI test

**Out of scope (separate work items)**:
- HTTPS/TLS termination (reverse proxy like Traefik or Caddy — document as an advanced setup)
- Kubernetes / Helm chart (post-Docker Compose, if demand exists)
- Managed hosted deployment (separate infrastructure, separate plan)
- MCP server containerization (stdio model does not fit compose)
- IB Gateway container (user-managed, too many auth/display complexities)
- SQLite fallback for simpler deployments (Phase C item, CLI wizard)
- Log aggregation (ELK/Loki — enterprise concern)
- Backup automation (document `pg_dump` command, do not build tooling)

---

## Estimated Effort

| Step | Effort | Notes |
|---|---|---|
| 1. Backend Dockerfile | 30 min | Straightforward, main risk is scipy/cvxpy build time |
| 2. Frontend Dockerfile | 30 min | Two-stage build, pnpm workspace awareness |
| 3. nginx config | 15 min | Based on vite.config.ts proxy rules |
| 4. DB init script | 15 min | Shell script + volume mounts |
| 5. docker-compose.yml | 45 min | Main orchestration file, env var wiring |
| 6. .env.docker.example | 15 min | Template with documentation |
| 7. Dev override | 20 min | Override file + dev Dockerfile |
| 8. .dockerignore | 10 min | |
| 9. Health endpoint | 10 min | If not already present |
| 10. Documentation | 30 min | Quick start guide |
| Testing + debugging | 60 min | End-to-end verification, fix issues |
| **Total** | **~4-5 hours** | |

---

## Open Questions

1. **Python version**: Pin to 3.11 (minimum supported) or 3.12/3.13 (latest)? 3.11 is safest for compatibility. If all deps work on 3.13, we can bump.

2. **Multi-stage backend build**: Strip gcc/g++ from final image to save ~200MB? Low priority but improves image size. Can do in a follow-up.

3. **Sample data in schema.sql**: The current `schema.sql` includes `INSERT` statements with a specific user email. Should be moved to a separate seed file before open-source release (overlaps with C4 release scrub).

4. **FMP cache directory**: The `_default_cache_base()` function in `fmp/cache.py` resolves the cache path by checking for `settings.py` in the parent directory. Inside the container at `/app`, this resolves to `/app` which is correct. Verify this assumption during testing.

5. **IBKR on Linux Docker**: `host.docker.internal` does not resolve by default on Linux. Document the `--add-host` workaround or use `extra_hosts` in compose.

---

*This plan covers the Docker Compose containerization for self-hosting (B2 in the open-source launch roadmap). Implementation produces a single-command path from clone to running application.*
