# Factor Intelligence Engine - Implementation Architecture

> **Status:** ✅ IMPLEMENTED (Backend Phases 1-2 + MCP tools). Frontend extracted to separate plan.
>
> **Backend files:** `core/factor_intelligence.py` (1,580 lines), `services/factor_intelligence_service.py` (919 lines), `routes/factor_intelligence.py` (362 lines), `models/factor_intelligence_models.py`, `database/migrations/20250903_add_factor_intelligence.sql`
>
> **MCP tools (built post-plan, now the primary consumer):**
> - `mcp_tools/factor_intelligence.py` — `get_factor_analysis` (correlations, performance, returns) + `get_factor_recommendations` (single + portfolio mode) with section filtering
> - `mcp_tools/stock.py` — `analyze_stock` (standalone ticker analysis using factor proxies)
> - Plans: `docs/planning/completed/FACTOR_INTELLIGENCE_MCP_PLAN.md`, `docs/planning/completed/FACTOR_RETURNS_MCP_PLAN.md`
>
> **Frontend (Phases 3-5):** Extracted to `docs/planning/FACTOR_INTELLIGENCE_FRONTEND_PLAN.md`

## **Overview**

This document outlines the complete implementation architecture for the Factor Intelligence Engine, designed to integrate seamlessly with the existing FastAPI-based portfolio risk analysis system. The architecture follows established patterns while introducing new capabilities for factor analysis and user-defined factor groups.

## **Current Backend Architecture Analysis**

### **✅ Established Patterns Identified:**

1. **🚀 FastAPI Framework**: Modern async web framework with automatic OpenAPI docs
2. **📁 Modular Router Architecture**: Each domain has its own router (`/routes/*.py`)
3. **🔐 Consistent Authentication**: `get_current_user()` dependency injection pattern
4. **📊 Pydantic Models**: Request/response validation in `/models/` directory
5. **🎯 Service Layer**: Clean separation between API and business logic
6. **📝 Comprehensive Logging**: Decorators for performance, errors, and operations
7. **⚡ Rate Limiting**: Tier-based limits with `@limiter.limit()` decorators
8. **🗄️ Database-First**: PostgreSQL with user isolation and proper transactions

### **🔄 Integration Strategy**

The Factor Intelligence Engine will be implemented as **separate endpoints** following the existing modular architecture:

- `/api/factor-intelligence/*` - Factor analysis endpoints
- `/api/factor-groups/*` - User-defined factor group management

This approach ensures clean separation of concerns and maintains the established domain-based routing pattern.

### Factor Universe Enrichment
- Enrich factor ETFs with `asset_class` via SecurityTypeService (DB → YAML → hardcoded) to support
  include/exclude filters and portfolio‑aware offsets; exclude `cash` and currency proxies from analysis.
- Prefer dividend‑adjusted total‑return prices (fallback to close) across correlation and performance paths.

## **Implementation Components**

### Appendix: Asset ETF Proxies (Recommended)

To align non‑equity asset classes with total‑return methodology in Factor Intelligence, define
canonical ETFs per asset class in a single mapping file and load them into the factor universe.

Mapping source (DB‑first): `asset_etf_proxies` table with YAML fallback (`asset_etf_proxies.yaml`)

Example YAML (fallback if DB unavailable):
```yaml
# asset_etf_proxies.yaml
asset_classes:
  fixed_income:
    canonical:
      UST2Y: SHY    # 1–3Y Treasuries (short)
      UST5Y: IEI    # 3–7Y Treasuries
      UST10Y: IEF   # 7–10Y Treasuries
      UST30Y: TLT   # 20+Y Treasuries
    alternates:
      UST30Y_alt: EDV   # Zero‑coupon long duration (optional)
      CASH: SGOV        # Bills (cash‑like; optional)

  commodity:
    canonical:
      broad: DBC
      gold: GLD
      silver: SLV
    # alternates: { energy: XLE, base_metals: DBB }  # optional

  crypto:
    canonical:
      BTC: BTC_SPOT_ETF  # e.g., IBIT/FBTC; use actual ticker in deployment
      ETH: ETH_SPOT_ETF  # e.g., ETHA/other; use actual ticker in deployment
```

Integration notes:
- Database‑first loader: Factor universe builder first queries `asset_etf_proxies` table, then falls back to YAML,
  and finally to a hardcoded minimal set if both are unavailable.
- Categorize as `fixed_income`, `commodity`, and `crypto` when loading into the universe.
- Tag with asset_class via SecurityTypeService for consistency (bond, commodity, crypto).
- Use in standard ETF→ETF matrices/performance (with dividend_yield).
- Keep macro Δy series for the separate `rate_sensitivity` correlations; do not mix Δy into ETF→ETF matrices.

### Database Migration: `/database/migrations/20250901_add_asset_etf_proxies.sql`

```sql
-- Create canonical asset ETF proxy catalog (database‑first loader with YAML fallback)
CREATE TABLE IF NOT EXISTS asset_etf_proxies (
    id SERIAL PRIMARY KEY,
    asset_class VARCHAR(50) NOT NULL,         -- 'fixed_income', 'commodity', 'crypto'
    proxy_key   VARCHAR(100) NOT NULL,        -- e.g., 'UST10Y', 'gold', 'BTC'
    etf_ticker  VARCHAR(20) NOT NULL,         -- canonical ETF ticker
    is_canonical BOOLEAN DEFAULT TRUE,        -- allow alternates with lower priority
    priority    INT DEFAULT 100,              -- lower number = higher priority
    description TEXT,
    updated_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(asset_class, proxy_key, etf_ticker)
);

CREATE INDEX IF NOT EXISTS idx_asset_etf_proxies_class ON asset_etf_proxies(asset_class);
CREATE INDEX IF NOT EXISTS idx_asset_etf_proxies_priority ON asset_etf_proxies(asset_class, priority);
```

### Database Migration: `/database/migrations/20250902_alter_industry_proxies_add_sector_group.sql`

```sql
-- Add explicit sector/group bucketing for industries (DB‑first, YAML fallback)
ALTER TABLE IF EXISTS industry_proxies
    ADD COLUMN IF NOT EXISTS sector_group VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_industry_proxies_sector_group ON industry_proxies(sector_group);
```

### Database Client Additions (planned)

```python
# inputs/database_client.py (new/extended methods)
def get_asset_etf_proxies(self) -> Dict[str, Dict[str, str]]:
    """Return {asset_class: {proxy_key: etf_ticker}} from database (canonical only)."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT asset_class, proxy_key, etf_ticker
                FROM asset_etf_proxies
                WHERE is_canonical = TRUE
                ORDER BY asset_class, priority DESC, proxy_key
                """
            )
            proxies: Dict[str, Dict[str, str]] = {}
            for row in cursor.fetchall():
                proxies.setdefault(row["asset_class"], {})[row["proxy_key"]] = row["etf_ticker"]
            return proxies
        except Exception as e:
            raise DatabaseError(f"Failed to fetch asset ETF proxies: {e}")

def upsert_asset_etf_proxy(
    self,
    asset_class: str,
    proxy_key: str,
    etf_ticker: str,
    is_canonical: bool = True,
    priority: int = 100,
    description: str | None = None,
):
    """Insert/update a single proxy row using INSERT ... ON CONFLICT."""
    from core.constants import VALID_ASSET_CLASSES
    if asset_class not in VALID_ASSET_CLASSES:
        raise ValueError(f"Invalid asset_class: {asset_class}. Must be one of: {VALID_ASSET_CLASSES}")

    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO asset_etf_proxies (asset_class, proxy_key, etf_ticker, is_canonical, priority, description, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (asset_class, proxy_key, etf_ticker)
                DO UPDATE SET
                    is_canonical = EXCLUDED.is_canonical,
                    priority     = EXCLUDED.priority,
                    description  = EXCLUDED.description,
                    updated_at   = NOW()
                """,
                (asset_class, proxy_key, etf_ticker.upper(), is_canonical, priority, description),
            )
            # Optional: enforce single canonical per (asset_class, proxy_key)
            # cursor.execute(
            #     """
            #     UPDATE asset_etf_proxies
            #     SET is_canonical = FALSE, updated_at = NOW()
            #     WHERE asset_class = %s AND proxy_key = %s AND etf_ticker <> %s AND is_canonical = TRUE
            #     """,
            #     (asset_class, proxy_key, etf_ticker.upper()),
            # )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise DatabaseError(f"Failed to upsert asset ETF proxy {asset_class}.{proxy_key}: {e}")

def update_industry_proxy(
    self,
    industry: str,
    proxy_etf: str,
    asset_class: str | None = None,
    sector_group: str | None = None,
) -> None:
    """Upsert industry proxy with optional asset_class and sector_group (ON CONFLICT)."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO industry_proxies (industry, proxy_etf, asset_class, sector_group, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (industry) DO UPDATE SET
                    proxy_etf    = EXCLUDED.proxy_etf,
                    asset_class  = EXCLUDED.asset_class,
                    sector_group = EXCLUDED.sector_group,
                    updated_at   = NOW()
                """,
                (industry, proxy_etf.upper(), asset_class, sector_group),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise DatabaseError(f"Failed to update industry proxy {industry}: {e}")
```

### Factor Universe Loader (update)

```python
# Pseudocode
@functools.lru_cache(maxsize=128)  # Global cache for shared reference data
def load_asset_class_proxies() -> Dict[str, Dict[str, str]]:
    try:
        proxies = db_client.get_asset_etf_proxies()  # DB‑first
        source = 'database'
    except Exception:
        proxies = load_yaml('asset_etf_proxies.yaml')  # YAML fallback
        source = 'yaml'
    if not proxies:
        proxies = HARD_CODED_MINIMAL_ASSET_PROXIES
        source = 'hardcoded'
    return proxies, source

@functools.lru_cache(maxsize=128)  # Global cache for shared reference data
def load_industry_buckets() -> Dict[str, str]:
    """Return {industry_name: sector_group} DB‑first from industry_proxies.sector_group; no YAML required.
    Industries without a sector_group are omitted; callers fall back to 'industry' for those entries.
    """
```

### Admin Tooling: Reference Data Sync (planned)

Add admin commands to keep database and YAML in sync for asset class ETF proxies, mirroring existing
patterns used for cash, exchange, and industry mappings.

Files:
- `admin/manage_reference_data.py` (extend)
- `admin/migrate_reference_data.py` (extend)
- `admin/README.md` (document commands)

Admin tool commands (manage_reference_data.py extensions):

```python
# New asset-proxy command group implementation

@click.group(name="asset-proxy")
def asset_proxy_commands():
    """Manage asset ETF proxies (fixed_income, commodity, crypto, etc.)"""
    pass

@asset_proxy_commands.command("list")
@click.option("--asset-class", help="Filter by specific asset class")
@click.option("--format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def list_asset_proxies(asset_class, format):
    """Lists all proxies grouped by asset_class using get_asset_etf_proxies()."""
    try:
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            proxies = db_client.get_asset_etf_proxies()

        if asset_class:
            proxies = {k: v for k, v in proxies.items() if k == asset_class}

        if format == "json":
            click.echo(json.dumps(proxies, indent=2))
            return

        # Table format
        if not proxies:
            click.echo("No asset ETF proxies found.")
            return

        for asset_cls, proxy_dict in proxies.items():
            click.echo(f"\n📁 {asset_cls.upper()}")
            click.echo("─" * (len(asset_cls) + 4))

            for proxy_key, etf_ticker in proxy_dict.items():
                click.echo(f"  {proxy_key:<20} → {etf_ticker}")

        total_proxies = sum(len(proxies_dict) for proxies_dict in proxies.values())
        click.echo(f"\nTotal: {total_proxies} proxies across {len(proxies)} asset classes")

    except Exception as e:
        click.echo(f"❌ Failed to list asset proxies: {e}", err=True)
        raise click.Abort()

@asset_proxy_commands.command("add")
@click.argument("asset_class")
@click.argument("proxy_key")
@click.argument("etf_ticker")
@click.option("--alt", is_flag=True, help="Set as alternative (non-canonical) proxy")
@click.option("--priority", type=int, default=100, help="Priority (higher = preferred)")
@click.option("--desc", help="Optional description")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def add_asset_proxy(asset_class, proxy_key, etf_ticker, alt, priority, desc, force):
    """UPSERT a single proxy row via upsert_asset_etf_proxy()."""
    try:
        is_canonical = not alt  # --alt flag sets is_canonical=False

        # Confirmation unless --force
        if not force:
            canonical_info = "canonical" if is_canonical else "alternative"
            click.echo(f"Adding {canonical_info} proxy:")
            click.echo(f"  Asset class: {asset_class}")
            click.echo(f"  Proxy key: {proxy_key}")
            click.echo(f"  ETF ticker: {etf_ticker}")
            click.echo(f"  Priority: {priority}")
            if desc:
                click.echo(f"  Description: {desc}")

            if not click.confirm("Continue?"):
                click.echo("Cancelled.")
                return

        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            db_client.upsert_asset_etf_proxy(
                asset_class=asset_class,
                proxy_key=proxy_key,
                etf_ticker=etf_ticker,
                is_canonical=is_canonical,
                priority=priority,
                description=desc
            )

        status = "canonical" if is_canonical else "alternative"
        click.echo(f"✅ Added {status} proxy: {asset_class}.{proxy_key} → {etf_ticker}")

    except Exception as e:
        click.echo(f"❌ Failed to add proxy: {e}", err=True)
        raise click.Abort()

@asset_proxy_commands.command("sync-from-yaml")
@click.argument("yaml_path", default="asset_etf_proxies.yaml")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
def sync_from_yaml(yaml_path, dry_run):
    """Loads YAML and bulk UPSERTs into DB; prints summary of added/updated/unchanged entries."""
    import yaml
    from pathlib import Path

    try:
        yaml_file = Path(yaml_path)
        if not yaml_file.exists():
            click.echo(f"❌ File not found: {yaml_path}")
            raise click.Abort()

        with open(yaml_file, 'r') as f:
            data = yaml.safe_load(f)

        if 'asset_etf_proxies' not in data:
            click.echo(f"❌ No 'asset_etf_proxies' section found in {yaml_path}")
            raise click.Abort()

        proxies_data = data['asset_etf_proxies']
        total_count = 0
        success_count = 0

        if dry_run:
            click.echo(f"🔍 DRY RUN - Would sync from {yaml_path}:")
        else:
            click.echo(f"🔄 Syncing asset ETF proxies from {yaml_path}...")

        from database import get_db_session
        db_client = None if dry_run else DatabaseClient(get_db_session().__enter__())  # ensure a live conn in non-dry mode

        for asset_class, proxies in proxies_data.items():
            click.echo(f"\n📁 {asset_class.upper()}")

            for proxy_key, etf_ticker in proxies.items():
                total_count += 1

                if dry_run:
                    click.echo(f"  [DRY RUN] Would upsert: {proxy_key} → {etf_ticker}")
                    success_count += 1
                else:
                    try:
                        db_client.upsert_asset_etf_proxy(
                            asset_class=asset_class,
                            proxy_key=proxy_key,
                            etf_ticker=etf_ticker,
                            is_canonical=True,
                            priority=100,
                            description=f"Synced from {yaml_path}"
                        )
                        success_count += 1
                        click.echo(f"  ✅ {proxy_key} → {etf_ticker}")
                    except Exception as e:
                        click.echo(f"  ❌ Failed {proxy_key}: {e}")

        status = "Would sync" if dry_run else "Synced"
        click.echo(f"\n{status}: {success_count}/{total_count} proxies")

    except Exception as e:
        click.echo(f"❌ Sync failed: {e}", err=True)
        raise click.Abort()

@asset_proxy_commands.command("export-yaml")
@click.argument("yaml_path", default="asset_etf_proxies.yaml")
@click.option("--force", is_flag=True, help="Overwrite existing file")
def export_yaml(yaml_path, force):
    """Exports DB state to YAML in canonical schema."""
    import yaml
    from pathlib import Path

    try:
        yaml_file = Path(yaml_path)

        if yaml_file.exists() and not force:
            if not click.confirm(f"File {yaml_path} exists. Overwrite?"):
                click.echo("Cancelled.")
                return

        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            proxies = db_client.get_asset_etf_proxies()

        if not proxies:
            click.echo("No asset ETF proxies found in database.")
            return

        # Structure for YAML export
        export_data = {
            "asset_etf_proxies": proxies,
            "_metadata": {
                "exported_at": datetime.now().isoformat(),
                "total_asset_classes": len(proxies),
                "total_proxies": sum(len(proxy_dict) for proxy_dict in proxies.values())
            }
        }

        with open(yaml_file, 'w') as f:
            yaml.dump(export_data, f, default_flow_style=False, sort_keys=True)

        total_proxies = export_data["_metadata"]["total_proxies"]
        click.echo(f"✅ Exported {total_proxies} proxies to {yaml_path}")

    except Exception as e:
        click.echo(f"❌ Export failed: {e}", err=True)
        raise click.Abort()

@asset_proxy_commands.command("clear-class")
@click.argument("asset_class")
@click.option("--force", is_flag=True, help="Skip safety prompt")
def clear_class(asset_class, force):
    """Deletes all proxies for an asset class (safety prompt unless --force)."""
    try:
        db_client = DatabaseClient()

        # Check what would be deleted
        proxies = db_client.get_asset_etf_proxies()

        if asset_class not in proxies:
            click.echo(f"No proxies found for asset class: {asset_class}")
            return

        proxy_count = len(proxies[asset_class])

        # Safety prompt unless --force
        if not force:
            click.echo(f"⚠️  This will DELETE {proxy_count} proxies for asset class '{asset_class}':")
            for proxy_key, etf_ticker in proxies[asset_class].items():
                click.echo(f"  - {proxy_key} → {etf_ticker}")

            click.echo(f"\n❗ This action cannot be undone!")
            if not click.confirm("Are you sure you want to continue?"):
                click.echo("Cancelled.")
                return

        # Execute deletion
        from database import get_db_session
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM asset_etf_proxies WHERE asset_class = %s", (asset_class,))
            deleted_count = cursor.rowcount
            conn.commit()
            click.echo(f"✅ Deleted {deleted_count} proxies for asset class '{asset_class}'")

    except Exception as e:
        click.echo(f"❌ Clear failed: {e}", err=True)
        raise click.Abort()

# Extended industry command
@industry_commands.command("add")  # Extends existing industry command group
@click.argument("industry_name")
@click.argument("proxy_etf")
@click.option("--asset-class", help="Optional asset class override")
@click.option("--group", help="Optional sector group for granularity")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def add_industry_with_group(industry_name, proxy_etf, asset_class, group, force):
    """Upserts industry proxy with optional asset_class and sector_group (DB-first)."""
    try:
        # Confirmation unless --force
        if not force:
            click.echo(f"Adding/updating industry proxy:")
            click.echo(f"  Industry: {industry_name}")
            click.echo(f"  Proxy ETF: {proxy_etf}")
            if asset_class:
                click.echo(f"  Asset class: {asset_class}")
            if group:
                click.echo(f"  Sector group: {group}")

            if not click.confirm("Continue?"):
                click.echo("Cancelled.")
                return

        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            db_client.update_industry_proxy(
                industry=industry_name,
                proxy_etf=proxy_etf,
                asset_class=asset_class,
                sector_group=group
            )

        group_info = f" (group: {group})" if group else ""
        asset_info = f" (asset_class: {asset_class})" if asset_class else ""
        click.echo(f"✅ Updated industry: {industry_name} → {proxy_etf}{group_info}{asset_info}")

    except Exception as e:
        click.echo(f"❌ Failed to add industry: {e}", err=True)
        raise click.Abort()
```

Industry commands (extend existing):
- `industry add <industry_name> <proxy_etf> [--asset-class <name>] [--group <sector_group>]`
  - Upserts industry proxy with optional asset_class override and sector_group (DB‑first). YAML edits can include an
    optional `group:` field, which the migration tool will upsert into `industry_proxies.sector_group`.

Migration script extension:

```python
def migrate_asset_etf_proxies(db_client):
    """
    Reads asset_etf_proxies.yaml and UPSERTs rows into asset_etf_proxies table.

    Expected YAML structure:
    asset_etf_proxies:
      fixed_income:
        duration_short: "SHY"
        duration_long: "TLT"
        credit_investment_grade: "LQD"
      commodity:
        gold: "GLD"
        silver: "SLV"
        broad_commodity: "DBC"
      crypto:
        btc_spot: "IBIT"
        eth_spot: "ETHA"
    """
    import yaml
    import os
    from pathlib import Path

    yaml_path = Path("asset_etf_proxies.yaml")

    try:
        if not yaml_path.exists():
            portfolio_logger.warning(f"⚠️  {yaml_path} not found, skipping asset ETF proxy migration")
            return

        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        if 'asset_etf_proxies' not in data:
            portfolio_logger.warning(f"⚠️  No 'asset_etf_proxies' section in {yaml_path}, skipping")
            return

        proxies_data = data['asset_etf_proxies']
        total_count = 0
        success_count = 0

        portfolio_logger.info(f"🔄 Migrating asset ETF proxies from {yaml_path}...")

        from core.constants import VALID_ASSET_CLASSES
        for asset_class, proxies in proxies_data.items():
            if asset_class not in VALID_ASSET_CLASSES:
                portfolio_logger.warning(f"    ⚠️  Skipping invalid asset_class '{asset_class}' in YAML")
                continue
            portfolio_logger.info(f"  📁 Processing {asset_class}...")

            for proxy_key, etf_ticker in proxies.items():
                try:
                    # Use the new DatabaseClient method
                    db_client.upsert_asset_etf_proxy(
                        asset_class=asset_class,
                        proxy_key=proxy_key,
                        etf_ticker=etf_ticker,
                        is_canonical=True,
                        priority=100,
                        description=f"Migrated from {yaml_path}"
                    )
                    success_count += 1
                    portfolio_logger.info(f"    ✅ {asset_class}.{proxy_key} -> {etf_ticker}")

                except Exception as e:
                    portfolio_logger.error(f"    ❌ Failed {asset_class}.{proxy_key}: {e}")

                total_count += 1

        portfolio_logger.info(f"✅ Asset ETF proxy migration complete: {success_count}/{total_count} successful")

    except Exception as e:
        portfolio_logger.error(f"❌ Asset ETF proxy migration failed: {e}")
        raise

def migrate_industry_mappings(db_client):
    """
    Extended version of existing function to handle optional 'group:' field.

    Updated YAML structure supports:
    industry_to_etf:
      "Technology":
        proxy: "XLK"
        group: "growth"  # Optional sector_group
      "Healthcare":
        proxy: "XLV"
        group: "defensive"  # Optional sector_group
      "Energy":
        proxy: "XLE"
        # No group specified - sector_group remains NULL
    """
    import yaml
    from pathlib import Path

    yaml_path = Path("industry_to_etf.yaml")

    try:
        if not yaml_path.exists():
            portfolio_logger.warning(f"⚠️  {yaml_path} not found, skipping industry mapping migration")
            return

        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        if 'industry_to_etf' not in data:
            portfolio_logger.warning(f"⚠️  No 'industry_to_etf' section in {yaml_path}, skipping")
            return

        industry_data = data['industry_to_etf']
        total_count = 0
        success_count = 0

        portfolio_logger.info(f"🔄 Migrating industry mappings from {yaml_path}...")

        for industry, mapping_info in industry_data.items():
            try:
                # Handle both old format (string) and new format (dict)
                if isinstance(mapping_info, str):
                    # Old format: "Technology": "XLK"
                    proxy_etf = mapping_info
                    sector_group = None
                else:
                    # New format: "Technology": {"proxy": "XLK", "group": "growth"}
                    proxy_etf = mapping_info.get('proxy')
                    sector_group = mapping_info.get('group')  # Optional

                if not proxy_etf:
                    portfolio_logger.warning(f"    ⚠️  No proxy specified for {industry}, skipping")
                    continue

                # Use the extended DatabaseClient method
                db_client.update_industry_proxy(
                    industry=industry,
                    proxy_etf=proxy_etf,
                    asset_class="equity",  # Default for industries
                    sector_group=sector_group  # Will be None if not specified
                )

                success_count += 1
                group_info = f" (group: {sector_group})" if sector_group else ""
                portfolio_logger.info(f"    ✅ {industry} -> {proxy_etf}{group_info}")

            except Exception as e:
                portfolio_logger.error(f"    ❌ Failed {industry}: {e}")

            total_count += 1

        portfolio_logger.info(f"✅ Industry mapping migration complete: {success_count}/{total_count} successful")

    except Exception as e:
        portfolio_logger.error(f"❌ Industry mapping migration failed: {e}")
        raise
```

Validation & safety:
- Validate `asset_class` against `VALID_ASSET_CLASSES`.
- Validate ticker format; keep DB‑first precedence in loaders (DB → YAML → hardcoded).
- Do not auto‑delete DB entries not present in YAML during sync (no destructive ops by default).


### **1. 📁 New Router Module: `/routes/factor_intelligence.py`**

```python
"""
Factor Intelligence Routes - FastAPI Implementation

This module provides FastAPI routes for factor intelligence analysis and user-defined
factor group management, following the established modular router architecture.

Architecture Overview:
===================
- **Framework**: FastAPI with async/await patterns and automatic OpenAPI documentation
- **Authentication**: Session-based using database-backed AuthService with dependency injection
- **Data Storage**: All factor groups saved to PostgreSQL database with user isolation
- **Multi-User Support**: Complete user isolation - users only see their own factor groups
- **Data Validation**: Pydantic models for request/response validation and serialization
- **Error Handling**: FastAPI HTTPException with standardized error responses

Key Features:
============
1. **Factor Correlation Analysis**: Market-wide factor correlation matrices
2. **Factor Performance Profiling**: Risk/return characteristics for all factors
3. **Portfolio-Aware Recommendations**: Intelligent offset suggestions considering current exposures
4. **User-Defined Factor Groups**: Create custom factor indices with flexible weighting
5. **Market-Cap Weighting**: Realistic index-style weighting based on company size
6. **Data Quality Validation**: Minimum data requirements and exclusion tracking
7. **Comprehensive Caching**: Production-grade caching with 30-minute TTL

Security Model:
==============
- All endpoints require valid session authentication (FastAPI dependency injection)
- User identification via session cookies validated through get_current_user()
- Factor group data stored with user_id foreign key for strict isolation
- Automatic 401 HTTPException for invalid authentication

API Endpoints (Segmented Outputs + Cross‑Asset Views):
=============
Factor Intelligence Analysis:
- POST /api/factor-intelligence/correlations - Per‑category correlation matrices (industry/style/market/fixed_income/cash/commodity/crypto) + optional cross‑category mini‑matrix and a separate rate‑sensitivity matrix (ETF returns vs Δy)
 - Also returns macro matrices:
  • macro_composite_matrix (small, square composites across equity/fixed_income/cash/commodity/crypto)
  • macro_etf_matrix (square, curated ETFs across macro groups; optional and heavier)
- POST /api/factor-intelligence/performance - Per‑category performance profiles with yield (including fixed_income ETFs)
- POST /api/factor-intelligence/recommendations - Portfolio-aware offset recommendations

Factor Group Management:
- GET    /api/factor-groups - List user's factor groups
- POST   /api/factor-groups - Create new factor group
- GET    /api/factor-groups/{group_name} - Get specific factor group
- PUT    /api/factor-groups/{group_name} - Update factor group
- DELETE /api/factor-groups/{group_name} - Delete factor group
- POST   /api/factor-groups/{group_name}/validate - Validate factor group data quality

Dependencies:
============
- FactorIntelligenceService: Core factor analysis business logic
- AuthService: Database-backed user session management
- PortfolioManager: Database-mode portfolio storage and retrieval
- PostgreSQL: User and factor group data persistence
- FastAPI: Modern async web framework with automatic validation
- Pydantic: Data validation and serialization
- Existing SlowAPI limiter: Uses established rate limiting from app.py

Usage:
=====
This router is included in the main FastAPI app:
```python
from routes.factor_intelligence import factor_intelligence_router, factor_groups_router
app.include_router(factor_intelligence_router)
app.include_router(factor_groups_router)


Developer Notes:
===============
- All route handlers are async functions with proper error handling
- Date ranges use PORTFOLIO_DEFAULTS from settings.py (no hardcoded dates)
- Factor group naming follows user-defined convention with validation
- Comprehensive docstrings with request/response examples and error codes
- Rate limiting follows existing tier-based patterns
- Logging decorators ensure comprehensive monitoring and debugging
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

# Import core services following existing patterns
from services.factor_intelligence_service import FactorIntelligenceService
from services.auth_service import auth_service
from core.data_objects import FactorAnalysisData, PortfolioData
from core.exceptions import ServiceError, FactorAnalysisError

# Import existing rate limiter from app.py following established pattern
from app import limiter

# Import logging infrastructure
from utils.logging import portfolio_logger

# === RATE LIMITING ARCHITECTURE ===
#
# Uses existing SlowAPI limiter from app.py following established patterns.
# The limiter is already configured with tier-based key function and works
# perfectly with all existing routes.
#
# Import pattern for new routes:
# ```python
# from app import limiter
# ```
#
# Route decorators use existing tier-based limits:
# - Format: "public_limit;registered_limit;paid_limit"
# - Example: @limiter.limit("50/day;100/day;200/day")

# === PYDANTIC MODELS FOR REQUEST/RESPONSE VALIDATION ===

class FactorCorrelationRequest(BaseModel):
    """Request model for factor correlation analysis.

    Attributes:
        start_date: Analysis start date (YYYY-MM-DD format, defaults to PORTFOLIO_DEFAULTS)
        end_date: Analysis end date (YYYY-MM-DD format, defaults to PORTFOLIO_DEFAULTS)
        max_factors: Maximum factors to include in formatted table (default: 15, range: 5-100)

    Example:
        {
            "start_date": "2019-01-01",
            "end_date": "2024-12-31",
            "max_factors": 20
        }
    """
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_factors: int = Field(default=15, ge=5, le=100, description="Maximum factors in formatted table")

class FactorCorrelationResponse(BaseModel):
    """Response model for factor correlation analysis.

    Attributes:
        success: Whether the analysis completed successfully
        correlation_matrix: Factor-to-factor correlation matrix (JSON serializable)
        formatted_table: Human-readable correlation table for Claude/display
        analysis_metadata: Analysis configuration and timing information
        error: Error message if analysis failed

    Example:
        {
            "success": true,
            "correlation_matrix": {"XLK": {"XLF": -0.12, "XLU": -0.34}, ...},
            "formatted_table": "FACTOR CORRELATION MATRIX\n...",
            "analysis_metadata": {"start_date": "2019-01-01", "factors_analyzed": 187}
        }
    """
    success: bool
    correlation_matrix: Optional[Dict[str, Any]] = None
    formatted_table: Optional[str] = None
    analysis_metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class FactorPerformanceRequest(BaseModel):
    """Request model for factor performance profiling.

    Attributes:
        start_date: Analysis start date (YYYY-MM-DD format)
        end_date: Analysis end date (YYYY-MM-DD format)
        benchmark_ticker: Benchmark for performance comparison (default: SPY)
        sort_by: Metric to sort results by (sharpe_ratio, annual_return, volatility)
    """
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    benchmark_ticker: str = "SPY"
    sort_by: str = Field(default="sharpe_ratio", regex="^(sharpe_ratio|annual_return|volatility)$")

class FactorPerformanceResponse(BaseModel):
    """Response model for factor performance profiling."""
    success: bool
    performance_profiles: Optional[Dict[str, Dict[str, float]]] = None
    formatted_table: Optional[str] = None
    analysis_metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class OffsetRecommendationRequest(BaseModel):
    """Request model for offset recommendations.

    Attributes:
        overexposed_factor: Factor that needs hedging/offset
        start_date: Analysis period start date
        end_date: Analysis period end date
        correlation_threshold: Maximum correlation for offset candidates (default: -0.2)
        max_recommendations: Maximum number of recommendations (default: 10)
    """
    overexposed_factor: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    correlation_threshold: float = Field(default=-0.2, ge=-1.0, le=0.0)
    max_recommendations: int = Field(default=10, ge=1, le=50)

class OffsetRecommendationResponse(BaseModel):
    """Response model for offset recommendations."""
    success: bool
    overexposed_factor: Optional[str] = None
    recommendations: Optional[List[Dict[str, Any]]] = None
    formatted_table: Optional[str] = None
    analysis_metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# Import logging decorators following existing patterns
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling,
    log_resource_usage_decorator
)

# Create routers following existing pattern
factor_intelligence_router = APIRouter(
    prefix='/api/factor-intelligence',
    tags=['factor-intelligence']
)

factor_groups_router = APIRouter(
    prefix='/api/factor-groups',
    tags=['factor-groups']
)

# Authentication dependency following existing pattern
def get_current_user(request: Request):
    """Get current authenticated user - follows existing auth pattern"""
    session_id = request.cookies.get('session_id')
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

# User-scoped service management following existing pattern
import threading
from typing import Dict

_user_factor_intelligence_services: Dict[int, FactorIntelligenceService] = {}
_user_services_lock = threading.Lock()

def get_user_factor_intelligence_service(user: dict) -> FactorIntelligenceService:
    """
    Get or create a FactorIntelligenceService instance for the current user.

    Each user gets their own FactorIntelligenceService instance with isolated caching.
    This prevents data leakage between users while maintaining per-user cache performance.

    Args:
        user: Current authenticated user from FastAPI dependency

    Returns:
        FactorIntelligenceService: User-specific service instance with isolated cache
    """
    user_id = user['user_id']

    with _user_services_lock:
        if user_id not in _user_factor_intelligence_services:
            _user_factor_intelligence_services[user_id] = FactorIntelligenceService(cache_results=True)
            portfolio_logger.info(f"🔐 Created FactorIntelligenceService for user {user_id}")

        return _user_factor_intelligence_services[user_id]

# Import limiter for rate limiting
from app import limiter

# === FACTOR INTELLIGENCE ANALYSIS ENDPOINTS ===

@log_portfolio_operation_decorator("factor_correlations")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=False)
@log_performance(10.0)
@log_error_handling("high")
@limiter.limit("100 per day;200 per day;500 per day")  # public;registered;paid
@factor_intelligence_router.post("/correlations", response_model=FactorCorrelationResponse)
async def analyze_factor_correlations(
    correlation_request: FactorCorrelationRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    service: FactorIntelligenceService = Depends(lambda user=Depends(get_current_user): get_user_factor_intelligence_service(user))
) -> FactorCorrelationResponse:
    """
    Analyze Factor Correlations with Enhanced Security & Monitoring
    
    Calculates correlation matrix between all factor proxies for market intelligence
    and offset recommendation analysis. Results are cached for 30 minutes to avoid
    expensive recalculation of 200+ factor correlations.
    
    HTTP Method: GET
    Route: /api/factor-intelligence/correlations
    Authentication: Required (user session)
    
    Query Parameters:
    ================
    start_date : str, optional
        Analysis start date (YYYY-MM-DD format, defaults to PORTFOLIO_DEFAULTS)
    end_date : str, optional  
        Analysis end date (YYYY-MM-DD format, defaults to PORTFOLIO_DEFAULTS)
    max_factors : int, optional
        Maximum factors to include in formatted table (default: 15, range: 5-100)
    
    Returns:
    =======
    JSON Response (segmented):
        success (bool): Operation success indicator
        matrices (dict): Per‑category correlation matrices (including 'rate' when requested),
          e.g. {"industry": {...}, "style": {...}, "market": {...}, "rate": {"UST2Y": {"UST5Y": 0.92, ...}, ...}}
        rate_sensitivity (dict): Cross‑category correlations: corr(ETF returns, Δy) with keys as ETFs and columns as maturities
        data_quality (dict): Information about excluded factors and data coverage
        formatted_table (str): CLI-formatted table for Claude AI integration
        analysis_metadata (dict): Analysis configuration and timing information
    
    Performance:
    ===========
    - First call: ~5-8 seconds (calculates 200+ factor correlations)
    - Cached calls: ~10-20ms (cache hit from service layer)
    - Cache TTL: 30 minutes with automatic invalidation
    
    Example Response:
    ================
    ```json
    {
      "success": true,
      "matrices": {
        "industry": {
          "Real Estate": {"Utilities": -0.32, "Technology": 0.15, ...},
          "Utilities": {"Real Estate": -0.32, "Technology": -0.18, ...}
        },
        "style": {
          "Momentum_US": {"Value_US": -0.12, ...}
        },
        "market": {
          "US_Market": {"Developed ex-US": 0.76, ...}
        }
      },
      "rate_sensitivity": {
        "XLU":  {"UST2Y": -0.35, "UST5Y": -0.42, "UST10Y": -0.48, "UST30Y": -0.41},
        "XLRE": {"UST2Y": -0.22, "UST5Y": -0.29, "UST10Y": -0.36, "UST30Y": -0.33}
      },
      "data_quality": {
        "factors_analyzed": 187,
        "factors_excluded": 13,
        "excluded_factor_list": ["FACTOR_X (insufficient data)", ...],
        "observations": 72,
        "data_coverage_pct": 93.5
      },
      "formatted_table": "FACTOR CORRELATIONS (segmented)\\n...",
      "analysis_metadata": {
        "start_date": "2019-01-31",
        "end_date": "2025-06-27",
        "analysis_date": "2024-01-15T10:30:00Z",
        "categories": ["industry","style","market","rate"],
        "user_id": 123
      }
    }
    ```
    """
    
    try:
        # Business validation (in addition to Pydantic field validation)
        if correlation_request.max_factors > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 factors allowed for performance reasons")

        # Extract user identifiers for logging
        user_id = user['user_id']
        user_email = user.get('email', 'unknown')

        # Log the request
        portfolio_logger.info(f"🔗 Factor correlation analysis requested by user {user_id} ({user_email})")

        # Create analysis data object from request
        analysis_data = FactorAnalysisData(
            start_date=correlation_request.start_date,
            end_date=correlation_request.end_date,
            use_database=True
        )

        # Call service layer for factor correlation analysis
        result = service.analyze_factor_correlations(analysis_data)

        # Return structured response following existing pattern
        return FactorCorrelationResponse(
            success=True,
            correlation_matrix=result.correlation_matrix.to_dict(),
            formatted_table=result.to_cli_report(),
            analysis_metadata=result.analysis_metadata
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions without modification
        raise
    except Exception as e:
        # Log security-relevant errors
        log_auth_event(
            user_id=user['user_id'],
            event_type="factor_analysis_error",
            provider="session",
            success=False,
            details={
                'error_type': type(e).__name__,
                'error_message': str(e),
                'endpoint': '/api/factor-intelligence/correlations'
            }
        )
        
        # Log workflow failure
        log_workflow_state("correlation_analysis_failed", "factor_correlation_analysis", {
            "user_id": user['user_id'],
            "error_type": type(e).__name__,
            "error_message": str(e)
        })
        
        # Log service health degradation
        log_service_health("factor_intelligence", "unhealthy", None, {
            "endpoint": "/correlations",
            "operation": "factor_correlations",
            "error": str(e),
            "error_type": type(e).__name__
        })
        
        raise HTTPException(status_code=500, detail=f"Factor correlation analysis failed: {str(e)}")

@factor_intelligence_router.get("/performance")
@limiter.limit("50 per day;100 per day;200 per day")
@log_api_health("FactorIntelligence", "performance")
@log_error_handling("high")
@log_portfolio_operation_decorator("api_factor_performance")
@log_cache_operations("factor_performance")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(15.0)
@log_workflow_state_decorator("factor_performance_analysis")
async def analyze_factor_performance(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    benchmark_ticker: str = "SPY",
    user: dict = Depends(get_current_user),
    service: FactorIntelligenceService = Depends(lambda user=Depends(get_current_user): get_user_factor_intelligence_service(user))
):
    """
    Analyze Factor Performance Profiles
    
    Calculates risk/return characteristics for all factor proxies including volatility,
    Sharpe ratios, maximum drawdown, and other performance metrics. Results provide
    market intelligence for factor selection and offset recommendations.
    
    HTTP Method: GET
    Route: /api/factor-intelligence/performance
    Authentication: Required (user session)
    
    Query Parameters:
    ================
    start_date : str, optional
        Analysis start date (YYYY-MM-DD format, defaults to PORTFOLIO_DEFAULTS)
    end_date : str, optional
        Analysis end date (YYYY-MM-DD format, defaults to PORTFOLIO_DEFAULTS)  
    benchmark_ticker : str, optional
        Benchmark for relative performance analysis (default: "SPY")
    
    Returns:
    =======
    JSON Response (segmented):
        success (bool): Operation success indicator
        performance_profiles (dict): Per‑category metrics, e.g. {"industry": {...}, "style": {...}, "market": {...}}
        composite_performance (dict, optional): Composite performance tables
            - macro: equity/fixed_income/cash/commodity/crypto composites
            - category: per‑category composites (industry/style/market/etc.)
        data_quality (dict): Information about excluded factors and data coverage
        formatted_table (str): CLI-formatted table for Claude AI integration (can be per‑category or combined)
        analysis_metadata (dict): Analysis configuration and timing information
        
    Performance Metrics Included:
    ============================
    - Annual Return: Annualized total return
    - Volatility: Annualized standard deviation
    - Sharpe Ratio: Risk-adjusted return measure
    - Maximum Drawdown: Largest peak-to-trough decline
    - Beta vs Benchmark: Market sensitivity measure
    - Alpha vs Benchmark: Excess return measure
    - Dividend Yield: Trailing current yield of factor ETF (when available)

    Dividend Yield Signal Quality (applied when ranking with prefer_income/min_dividend_yield):
    - Asset-class aware usage:
      • Consider yields for equity, fixed_income, and cash ETFs.
      • Ignore commodity/crypto ETF yields by default (treat as 0) unless explicitly whitelisted.
    - Sanity checks:
      • Clamp negative yields to 0.0; drop implausible outliers (reuse existing outlier guards in data layer).
      • For cash ETFs, expect short‑rate range; for bond ETFs, prefer reasonable ranges (e.g., 0–15%).
      • If multiple sources become available later (e.g., SEC yield vs TTM), prefer SEC yield for fixed_income if exposed.
    - Data quality:
      • Missing or filtered yields default to 0.0 and are reported in data_quality warnings.
    
    Example Response:
    ================
    ```json
    {
      "success": true,
      "performance_profiles": {
        "industry": {
          "Real Estate": {"annual_return": 0.085, "volatility": 0.22, "sharpe_ratio": 0.38, "max_drawdown": -0.45, "beta_vs_benchmark": 1.15, "dividend_yield": 0.032},
          "Utilities":   {"annual_return": 0.065, "volatility": 0.16, "sharpe_ratio": 0.41, "max_drawdown": -0.28, "beta_vs_benchmark": 0.75, "dividend_yield": 0.036}
        },
        "style": {
          "Momentum_US": {"annual_return": 0.102, "volatility": 0.19, "sharpe_ratio": 0.54, "max_drawdown": -0.31, "beta_vs_benchmark": 1.08, "dividend_yield": 0.009}
        },
        "market": {
          "US_Market":   {"annual_return": 0.115, "volatility": 0.18, "sharpe_ratio": 0.62, "max_drawdown": -0.34, "beta_vs_benchmark": 1.00, "dividend_yield": 0.015}
        }
      },
      "composite_performance": {
        "macro": {
          "equity": {"annual_return": 0.118, "volatility": 0.185, "sharpe_ratio": 0.64, "max_drawdown": -0.33, "dividend_yield": 0.015},
          "fixed_income": {"annual_return": 0.034, "volatility": 0.065, "sharpe_ratio": 0.42, "max_drawdown": -0.09, "dividend_yield": 0.028},
          "cash": {"annual_return": 0.045, "volatility": 0.010, "sharpe_ratio": 0.50, "max_drawdown": -0.01, "dividend_yield": 0.045}
        },
        "category": {
          "industry": {
            "Real Estate": {"annual_return": 0.072, "volatility": 0.162, "sharpe_ratio": 0.35, "max_drawdown": -0.29, "dividend_yield": 0.032},
            "Utilities":   {"annual_return": 0.065, "volatility": 0.140, "sharpe_ratio": 0.40, "max_drawdown": -0.24, "dividend_yield": 0.036}
          },
          "style": {
            "Momentum_US": {"annual_return": 0.102, "volatility": 0.190, "sharpe_ratio": 0.54, "max_drawdown": -0.31, "dividend_yield": 0.009}
          }
        }
      },
      "formatted_table": "FACTOR PERFORMANCE PROFILES (segmented)\n...",
      "analysis_metadata": {"categories": ["industry","style","market"], ...}
    }
    ```
    """
    try:
        # Create analysis data object
        analysis_data = FactorAnalysisData.from_dates(
            start_date=start_date,
            end_date=end_date,
            benchmark_ticker=benchmark_ticker
        )
        
        # Call service layer for factor performance analysis
        result = service.analyze_factor_performance(analysis_data)
        
        # Return structured response
        return {
            "success": True,
            "performance_profiles": result.performance_profiles,
            "data_quality": result.data_quality,
            "formatted_table": result.to_formatted_table(),
            "analysis_metadata": result.analysis_metadata
        }
        
    except ServiceError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "error_code": "FACTOR_ANALYSIS_ERROR",
                "endpoint": "factor-intelligence/performance"
            }
        )
    except Exception as e:
        portfolio_logger.error(f"Factor performance analysis failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Factor performance analysis failed",
                "error_code": "INTERNAL_SERVER_ERROR",
                "endpoint": "factor-intelligence/performance"
            }
        )

@factor_intelligence_router.post("/recommendations")
@limiter.limit("30 per day;60 per day;120 per day")
@log_api_health("FactorIntelligence", "recommendations")
@log_error_handling("high")
@log_portfolio_operation_decorator("api_offset_recommendations")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=False)
@log_performance(8.0)
@log_workflow_state_decorator("portfolio_offset_recommendations")
async def generate_offset_recommendations(
    request: Request,
    recommendation_request: "OffsetRecommendationRequest",
    user: dict = Depends(get_current_user),
    service: FactorIntelligenceService = Depends(lambda user=Depends(get_current_user): get_user_factor_intelligence_service(user))
):
    """
    Generate Portfolio-Aware Offset Recommendations
    
    Provides intelligent hedging suggestions for overexposed factors by analyzing
    current portfolio exposures and recommending negatively correlated factors
    with attractive risk/return profiles.
    
    HTTP Method: POST
    Route: /api/factor-intelligence/recommendations
    Authentication: Required (user session)
    
    Request Body:
    ============
    ```json
    {
        "portfolio_name": "CURRENT_PORTFOLIO",
        "overexposed_factor": "Real Estate",
        "target_allocation_reduction": 0.10,
        "correlation_threshold": -0.2
    }
    ```
    
    Returns:
    =======
    JSON Response:
        success (bool): Operation success indicator
        recommendations (list): Ranked offset recommendations with allocation suggestions
        overexposed_factor (str): Factor being hedged
        current_portfolio_exposures (dict): Current factor exposures from portfolio analysis
        formatted_table (str): CLI-formatted recommendations for Claude AI integration
        analysis_metadata (dict): Analysis configuration and portfolio context
        
    Recommendation Logic:
    ====================
    1. Analyze current portfolio factor exposures
    2. Find factors with negative correlation to overexposed factor
    3. Filter out factors already overexposed in current portfolio
    4. Rank by risk-adjusted return characteristics
    5. Suggest specific allocation amounts considering current exposures
    
    Example Response:
    ================
    ```json
    {
        "success": true,
        "recommendations": [
            {
                "factor": "Utilities",
                "etf_ticker": "XLU",
                "correlation_to_overexposed": -0.34,
                "current_portfolio_exposure": 0.05,
                "suggested_additional_allocation": 0.08,
                "sharpe_ratio": 0.72,
                "max_drawdown": -0.12,
                "rationale": "Strong negative correlation with low current exposure"
            }
        ],
        "overexposed_factor": "Real Estate",
        "current_portfolio_exposures": {
            "Real Estate": 0.35,
            "Technology": 0.25,
            "Utilities": 0.05
        },
        "formatted_table": "OFFSET RECOMMENDATIONS\\n...",
        "analysis_metadata": {...}
    }
    ```
    """
    try:
        # Load portfolio data for current exposures
        from inputs.portfolio_manager import PortfolioManager
        pm = PortfolioManager(use_database=True, user_id=user['user_id'])
        portfolio_data = pm.load_portfolio_data(recommendation_request.portfolio_name)
        
        # Create analysis data object
        analysis_data = FactorAnalysisData.from_defaults()
        
        # Call service layer for offset recommendations
        result = service.generate_portfolio_aware_recommendations(
            overexposed_factor=recommendation_request.overexposed_factor,
            portfolio_data=portfolio_data,
            analysis_data=analysis_data,
            target_allocation_reduction=recommendation_request.target_allocation_reduction,
            correlation_threshold=recommendation_request.correlation_threshold
        )
        
        # Return structured response
        return {
            "success": True,
            "recommendations": result.recommendations,
            "overexposed_factor": result.overexposed_factor,
            "current_portfolio_exposures": result.current_portfolio_exposures,
            "formatted_table": result.to_formatted_table(),
            "analysis_metadata": result.analysis_metadata
        }
        
    except ServiceError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "error_code": "OFFSET_RECOMMENDATION_ERROR",
                "endpoint": "factor-intelligence/recommendations"
            }
        )
    except Exception as e:
        portfolio_logger.error(f"Offset recommendation generation failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Offset recommendation generation failed",
                "error_code": "INTERNAL_SERVER_ERROR",
                "endpoint": "factor-intelligence/recommendations"
            }
        )

# === FACTOR GROUP MANAGEMENT ENDPOINTS ===

@factor_groups_router.get("")
@limiter.limit("100 per day;200 per day;500 per day")
@log_api_health("FactorGroups", "list")
@log_error_handling("medium")
@log_portfolio_operation_decorator("api_list_factor_groups")
@log_cache_operations("factor_groups_list")
@log_performance(1.0)
async def list_factor_groups(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    List User's Factor Groups
    
    Retrieves all factor groups created by the authenticated user with metadata
    including creation dates, weighting methods, and validation status.
    
    HTTP Method: GET
    Route: /api/factor-groups
    Authentication: Required (user session)
    
    Returns:
    =======
    JSON Response:
        success (bool): Operation success indicator
        factor_groups (list): List of user's factor groups with metadata
        count (int): Total number of factor groups
        
    Example Response:
    ================
    ```json
    {
        "success": true,
        "factor_groups": [
            {
                "group_name": "My Tech Basket",
                "description": "Large-cap technology stocks",
                "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN"],
                "weighting_method": "market_cap",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "is_valid": true,
                "ticker_count": 4
            }
        ],
        "count": 1
    }
    ```
    """
    try:
        # Get factor groups from database
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            factor_groups = db_client.get_user_factor_groups(user['user_id'])
        
        # Format response
        return {
            "success": True,
            "factor_groups": factor_groups,
            "count": len(factor_groups)
        }
        
    except Exception as e:
        portfolio_logger.error(f"Failed to list factor groups: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to retrieve factor groups",
                "error_code": "INTERNAL_SERVER_ERROR",
                "endpoint": "factor-groups"
            }
        )

@factor_groups_router.post("")
@limiter.limit("20 per day;40 per day;80 per day")
@log_api_health("FactorGroups", "create")
@log_error_handling("high")
@log_portfolio_operation_decorator("api_create_factor_group")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(5.0)
@log_workflow_state_decorator("factor_group_creation")
async def create_factor_group(
    request: Request,
    group_request: "CreateFactorGroupRequest",
    user: dict = Depends(get_current_user)
):
    """
    Create New Factor Group
    
    Creates a user-defined factor group with specified tickers and weighting method.
    Validates data availability and calculates initial performance metrics.
    
    HTTP Method: POST
    Route: /api/factor-groups
    Authentication: Required (user session)
    
    Request Body:
    ============
    ```json
    {
        "group_name": "My Tech Basket",
        "description": "Large-cap technology stocks for factor analysis",
        "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN"],
        "weighting_method": "market_cap",
        "weights": null
    }
    ```
    
    Weighting Methods:
    =================
    - "equal": Equal weighting across all stocks (1/N each)
    - "market_cap": Market capitalization weighted (realistic index-style)
    - "custom": User-defined weights (requires weights parameter)
    
    Validation Rules:
    ================
    - Group name: 1-100 characters, unique per user
    - Tickers: 2-50 valid stock symbols
    - Data requirement: Minimum 24 months of price data per ticker
    - Weighting: Must sum to 1.0 for custom weights
    
    Returns:
    =======
    JSON Response:
        success (bool): Operation success indicator
        group_name (str): Created group name
        proxy_identifier (str): Factor proxy ID (e.g., "USER:My_Tech_Basket")
        validation_metadata (dict): Data quality and composition details
        created_at (datetime): Creation timestamp
        
    Example Response:
    ================
    ```json
    {
        "success": true,
        "group_name": "My Tech Basket",
        "proxy_identifier": "USER:My_Tech_Basket",
        "validation_metadata": {
            "tickers_included": ["AAPL", "MSFT", "GOOGL", "AMZN"],
            "tickers_excluded": [],
            "final_weights": {
                "AAPL": 0.35,
                "MSFT": 0.28,
                "GOOGL": 0.22,
                "AMZN": 0.15
            },
            "data_points": 72,
            "date_range": "2019-01-31 to 2025-06-27"
        },
        "created_at": "2024-01-15T10:30:00Z"
    }
    ```
    """
    try:
        # Validate and create factor group
        from core.factor_index import create_factor_proxy_from_group
        from settings import PORTFOLIO_DEFAULTS
        
        # Log factor group creation workflow
        workflow_id = f"factor_group_create_{user['user_id']}_{int(time.time())}"
        log_workflow_state(
            workflow_id,
            "validation_started",
            "in_progress",
            user_id=user['user_id'],
            details={
                "group_name": group_request.group_name,
                "ticker_count": len(group_request.tickers),
                "weighting_method": group_request.weighting_method
            }
        )
        
        # Create factor proxy and validate data
        proxy_id, metadata = create_factor_proxy_from_group(
            group_name=group_request.group_name,
            tickers=group_request.tickers,
            start_date=PORTFOLIO_DEFAULTS["start_date"],
            end_date=PORTFOLIO_DEFAULTS["end_date"],
            weights=group_request.weights,
            weighting_method=group_request.weighting_method
        )
        
        # Log validation success
        log_workflow_state(
            workflow_id,
            "validation_completed",
            "in_progress",
            user_id=user['user_id'],
            details={
                "proxy_id": proxy_id,
                "tickers_included": len(metadata.get("tickers_included", [])),
                "tickers_excluded": len(metadata.get("tickers_excluded", [])),
                "data_points": metadata.get("data_points", 0)
            }
        )
        
        # Log database save step
        log_workflow_state(
            workflow_id,
            "database_save_started",
            "in_progress",
            user_id=user['user_id'],
            details={"group_name": group_request.group_name}
        )
        
        # Save to database
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            group_id = db_client.create_user_factor_group(
                user_id=user['user_id'],
                group_name=group_request.group_name,
                description=group_request.description,
                tickers=group_request.tickers,
                weights=group_request.weights,
                weighting_method=group_request.weighting_method
            )
        
        # Log successful completion
        log_workflow_state(
            workflow_id,
            "factor_group_created",
            "completed",
            user_id=user['user_id'],
            details={
                "group_id": group_id,
                "group_name": group_request.group_name,
                "proxy_id": proxy_id
            }
        )
        
        # Return success response
        return {
            "success": True,
            "group_name": group_request.group_name,
            "proxy_identifier": proxy_id,
            "validation_metadata": metadata,
            "created_at": datetime.utcnow().isoformat()
        }
        
            except ValueError as e:
            # Log validation failure
            log_workflow_state(
                workflow_id,
                "validation_failed",
                "failed",
                user_id=user['user_id'],
                details={
                    "error": str(e),
                    "error_type": "ValidationError",
                    "group_name": group_request.group_name
                }
            )
            
            # Log service health issue
            log_service_health(
                "factor_groups",
                "degraded",
                details={
                    "operation": "create_factor_group",
                    "error": str(e),
                    "error_type": "ValidationError"
                }
            )
            
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(e),
                    "error_code": "FACTOR_GROUP_VALIDATION_ERROR",
                    "endpoint": "factor-groups"
                }
            )
        except Exception as e:
            # Log unexpected failure
            log_workflow_state(
                workflow_id,
                "creation_failed",
                "failed",
                user_id=user['user_id'],
                details={
                    "error": str(e),
                    "error_type": "UnexpectedError",
                    "group_name": group_request.group_name
                }
            )
            
            # Log service health failure
            log_service_health(
                "factor_groups",
                "unhealthy",
                details={
                    "operation": "create_factor_group",
                    "error": str(e),
                    "error_type": "UnexpectedError"
                }
            )
            
            portfolio_logger.error(f"Failed to create factor group: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Failed to create factor group",
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "endpoint": "factor-groups"
                }
            )

# Additional endpoints (GET, PUT, DELETE specific groups) would follow similar patterns...
```

### **2. 📊 Pydantic Models: `/models/factor_intelligence_models.py`**

```python
"""Pydantic models for Factor Intelligence API endpoints"""

from pydantic import BaseModel, Field, validator
from typing import Dict, Any, List, Optional
from datetime import datetime

# === REQUEST MODELS ===

class FactorCorrelationRequest(BaseModel):
    """Enhanced request model for factor correlation analysis with robust validation"""
    start_date: Optional[str] = Field(None, regex=r'^\d{4}-\d{2}-\d{2}$', description="Analysis start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, regex=r'^\d{4}-\d{2}-\d{2}$', description="Analysis end date (YYYY-MM-DD)")
    factor_universe: Optional[Dict[str, str]] = Field(None, description="Custom factor universe mapping")
    max_factors: int = Field(default=15, ge=5, le=100, description="Maximum factors in formatted table")
    min_observations: int = Field(default=24, ge=12, le=120, description="Minimum observations required per factor")
    correlation_threshold: float = Field(default=0.05, ge=0.0, le=1.0, description="Minimum correlation threshold for recommendations")
    asset_class_filters: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Optional asset class filters: {'include': [...], 'exclude': [...]}"
    )
    factor_categories: Optional[List[str]] = Field(
        default=None,
        description="Subset of categories to analyze (e.g., ['industry','style','market'])"
    )
    include_rate_sensitivity: bool = Field(
        default=True,
        description="Include rate-sensitivity matrix (ETF returns vs Δy)"
    )
    rate_maturities: Optional[List[str]] = Field(
        default=None,
        description="Key-rate maturities to include (defaults from RATE_FACTOR_CONFIG)"
    )
    include_market_sensitivity: bool = Field(
        default=True,
        description="Include market-sensitivity overlay (ETF returns vs market benchmarks)"
    )
    market_benchmarks: Optional[List[str]] = Field(
        default=["SPY"],
        description="Market benchmark tickers for sensitivity overlay (total-return series)"
    )
    market_sensitivity_categories: Optional[List[str]] = Field(
        default=None,
        description="Categories to include for market_sensitivity. Defaults to ['industry','style'] if not provided. 'market' is excluded by default and ETFs used as benchmarks are skipped."
    )
    include_macro_composite: bool = Field(
        default=True,
        description="Include macro composite matrix across equity/fixed_income/cash/commodity/crypto"
    )
    include_macro_etf: bool = Field(
        default=False,
        description="Include macro ETF matrix (curated ETFs across macro groups; heavier)"
    )
    macro_groups: Optional[List[str]] = Field(
        default=["equity","bond","cash","commodity","crypto"],
        description="Macro groups to include in macro matrices"
    )
    macro_max_per_group: int = Field(
        default=5, ge=1, le=20,
        description="Max ETFs per macro group for macro_etf_matrix"
    )
    macro_deduplicate_threshold: float = Field(
        default=0.95, ge=0.0, le=1.0,
        description="Within-group deduplication threshold (drop |corr| ≥ threshold)"
    )
    macro_min_group_coverage_pct: Optional[float] = Field(
        default=None,
        description="Minimum fraction of eligible ETFs per macro group that must pass data-quality filters to include the group (defaults read from settings.DATA_QUALITY_THRESHOLDS if omitted)"
    )
    # Output/customization controls
    sections: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of sections to compute/return, e.g., ['matrices:industry','overlays:rate','macro:composite']"
    )
    format: Optional[str] = Field(
        default='json',
        regex='^(json|table|both)$',
        description="Output format preference for table-capable views: json, table, or both"
    )
    top_n_per_matrix: Optional[int] = Field(
        default=15, ge=5, le=100,
        description="Limit rendered table size for matrices (does not affect JSON payloads)"
    )
    rate_sensitivity_categories: Optional[List[str]] = Field(
        default=None,
        description="Categories to include for rate_sensitivity. Defaults to ['fixed_income','industry','market','cash'] if not provided."
    )

    # Industry granularity controls
    industry_granularity: str = Field(
        default="group",
        regex="^(group|industry|subindustry)$",
        description="Industry granularity level: 'group' uses sector_group, 'industry' uses standard industry names, 'subindustry' is most granular"
    )

    # Rolling/stability and regime (future)
    include_rolling_summaries: bool = Field(
        default=False,
        description="Include rolling window correlation summaries for stability analysis"
    )
    rolling_windows: Optional[List[int]] = Field(
        default=None,
        description="Rolling window periods in months (e.g., [12,24,36]). Defaults to [12,24,36] if include_rolling_summaries is True"
    )
    regime: Optional[str] = Field(
        default=None,
        description="Reserved for future regime classifier integration"
    )

    @validator('end_date')
    def validate_date_range(cls, v, values):
        """Validate date range is logical and sufficient."""
        if v and 'start_date' in values and values['start_date']:
            start = datetime.fromisoformat(values['start_date'])
            end = datetime.fromisoformat(v)
            
            if start >= end:
                raise ValueError("End date must be after start date")
            
            if (end - start).days < 365:
                raise ValueError("Minimum 1 year analysis period required")
        
        return v
    
    @validator('factor_universe')
    def validate_factor_universe(cls, v):
        """Validate factor universe ticker symbols."""
        if v:
            for factor, ticker in v.items():
                clean_ticker = ticker.strip().upper()
                if not re.match(r'^[A-Z]{1,5}(\.[A-Z])?$|^CUR:[A-Z]{3}$', clean_ticker):
                    raise ValueError(f"Invalid ticker format for factor '{factor}': {ticker}")
        return v

    @validator('rolling_windows')
    def validate_rolling_windows(cls, v, values):
        """Ensure rolling_windows is provided when include_rolling_summaries is True."""
        include_rolling = values.get('include_rolling_summaries', False)
        if include_rolling and not v:
            # Set default rolling windows
            return [12, 24, 36]
        if v:
            # Validate window periods are reasonable
            for window in v:
                if not isinstance(window, int) or window < 6 or window > 120:
                    raise ValueError("Rolling windows must be integers between 6 and 120 months")
        return v

class FactorPerformanceRequest(BaseModel):
    """Enhanced request model for factor performance analysis with robust validation"""
    start_date: Optional[str] = Field(None, regex=r'^\d{4}-\d{2}-\d{2}$', description="Analysis start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, regex=r'^\d{4}-\d{2}-\d{2}$', description="Analysis end date (YYYY-MM-DD)")
    benchmark_ticker: str = Field(default="SPY", description="Benchmark ticker for relative performance")
    factor_universe: Optional[Dict[str, str]] = Field(None, description="Custom factor universe mapping")
    min_observations: int = Field(default=24, ge=12, le=120, description="Minimum observations required per factor")
    asset_class_filters: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Optional asset class filters: {'include': [...], 'exclude': [...]}"
    )
    factor_categories: Optional[List[str]] = Field(
        default=None,
        description="Subset of categories to analyze (e.g., ['industry','style','market'])"
    )
    # Note: Performance endpoint is returns-based; no rate betas are computed here.
    
    # Composite performance options
    include_macro_composite_performance: bool = Field(
        default=True,
        description="Include macro composite performance (equity/fixed_income/cash/commodity/crypto)"
    )
    include_factor_composite_performance: bool = Field(
        default=True,
        description="Include per-category composite performance tables (industry/style/market/etc.)"
    )
    composite_weighting_method: str = Field(
        default="equal",
        regex="^(equal|cap|custom)$",
        description="Composite weighting method: equal, cap (cap-weighted), or custom"
    )
    composite_max_per_group: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Optional cap on ETFs per group when building composites"
    )

    # Industry granularity controls (for composite performance)
    industry_granularity: str = Field(
        default="group",
        regex="^(group|industry|subindustry)$",
        description="Industry granularity level for composite performance calculation"
    )

    @validator('end_date')
    def validate_date_range(cls, v, values):
        """Validate date range is logical and sufficient."""
        return FactorCorrelationRequest.validate_date_range(v, values)
    
    @validator('factor_universe')
    def validate_factor_universe(cls, v):
        """Validate factor universe ticker symbols."""
        return FactorCorrelationRequest.validate_factor_universe(v)
    
    @validator('benchmark_ticker')
    def validate_benchmark_ticker(cls, v):
        """Validate benchmark ticker format."""
        clean_ticker = v.strip().upper()
        if not re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', clean_ticker):
            raise ValueError(f"Invalid benchmark ticker format: {v}")
        return clean_ticker

class OffsetRecommendationRequest(BaseModel):
    """Request model for portfolio-aware offset recommendations"""
    portfolio_name: str = Field(default="CURRENT_PORTFOLIO", description="Portfolio to analyze")
    overexposed_factor: str = Field(..., description="Factor to reduce exposure to")
    target_allocation_reduction: float = Field(
        default=0.10, 
        ge=0.01, 
        le=0.50, 
        description="Target reduction in factor allocation (0.01-0.50)"
    )
    correlation_threshold: float = Field(
        default=-0.2, 
        ge=-1.0, 
        le=0.0, 
        description="Maximum correlation for offset candidates (-1.0 to 0.0)"
    )
    asset_class_filters: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Optional asset class filters for hedges: {'include': [...], 'exclude': [...]}"
    )
    prefer_income: bool = Field(default=False, description="Bias hedges toward higher dividend yield")
    min_dividend_yield: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Minimum dividend yield for candidates (0.00-1.00)")
    factor_categories: Optional[List[str]] = Field(
        default=None,
        description="Subset of categories for candidate hedges (e.g., ['industry','style'])"
    )

class CreateFactorGroupRequest(BaseModel):
    """Request model for creating user-defined factor groups"""
    group_name: str = Field(..., min_length=1, max_length=100, description="Unique group name")
    description: Optional[str] = Field(None, max_length=500, description="Optional group description")
    tickers: List[str] = Field(..., min_items=2, max_items=50, description="Stock tickers (2-50)")
    weights: Optional[Dict[str, float]] = Field(None, description="Custom weights (only for weighting_method='custom')")
    weighting_method: str = Field(
        default="equal", 
        regex="^(equal|market_cap|custom)$",
        description="Weighting method: equal, market_cap, or custom"
    )
    
    @validator('weights')
    def validate_custom_weights(cls, v, values):
        """Validate custom weights when weighting_method is 'custom'"""
        if values.get('weighting_method') == 'custom':
            if not v:
                raise ValueError("Custom weights required when weighting_method is 'custom'")
            if abs(sum(v.values()) - 1.0) > 0.001:
                raise ValueError("Custom weights must sum to 1.0")
        return v
    
    @validator('tickers')
    def validate_tickers(cls, v):
        """Validate ticker symbols"""
        if len(set(v)) != len(v):
            raise ValueError("Duplicate tickers not allowed")
        for ticker in v:
            if not ticker.isalnum() or len(ticker) > 10:
                raise ValueError(f"Invalid ticker format: {ticker}")
        return v

class UpdateFactorGroupRequest(BaseModel):
    """Request model for updating existing factor groups"""
    description: Optional[str] = Field(None, max_length=500)
    tickers: Optional[List[str]] = Field(None, min_items=2, max_items=50)
    weights: Optional[Dict[str, float]] = None
    weighting_method: Optional[str] = Field(None, regex="^(equal|market_cap|custom)$")

# === RESPONSE MODELS ===

class FactorCorrelationResponse(BaseModel):
    """Response model for factor correlation analysis"""
    success: bool = True
    correlation_matrix: Dict[str, Dict[str, float]]
    data_quality: Dict[str, Any]
    formatted_table: str
    analysis_metadata: Dict[str, Any]

class FactorPerformanceResponse(BaseModel):
    """Response model for factor performance analysis"""
    success: bool = True
    performance_profiles: Dict[str, Dict[str, float]]
    data_quality: Dict[str, Any]
    formatted_table: str
    analysis_metadata: Dict[str, Any]

class OffsetRecommendationResponse(BaseModel):
    """Response model for offset recommendations"""
    success: bool = True
    recommendations: List[Dict[str, Any]]
    overexposed_factor: str
    current_portfolio_exposures: Dict[str, float]
    formatted_table: str
    analysis_metadata: Dict[str, Any]

class FactorGroupResponse(BaseModel):
    """Response model for factor group operations"""
    success: bool = True
    group_name: str
    proxy_identifier: Optional[str] = None
    tickers: List[str]
    weighting_method: str
    final_weights: Optional[Dict[str, float]] = None
    validation_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class FactorGroupListResponse(BaseModel):
    """Response model for listing factor groups"""
    success: bool = True
    factor_groups: List[Dict[str, Any]]
    count: int

class FactorGroupValidationResponse(BaseModel):
    """Response model for factor group validation"""
    success: bool = True
    is_valid: bool
    validation_metadata: Dict[str, Any]
    issues: List[str] = []
    warnings: List[str] = []
```

### **3. 🔗 Service Integration: Update `/services/service_manager.py`**

```python
"""Service Manager Integration for Factor Intelligence Engine"""

# Add to existing ServiceManager class
from services.factor_intelligence_service import FactorIntelligenceService

class ServiceManager:
    """
    Unified service manager for the risk analysis system.
    
    Updated to include Factor Intelligence Engine services alongside existing
    portfolio, optimization, stock, and scenario services with comprehensive
    health monitoring and performance tracking.
    """
    
    def __init__(self, cache_results: bool = True, enable_async: bool = True):
        """Initialize all services including Factor Intelligence Engine"""
        # ... existing service initialization ...
        
        # Add Factor Intelligence Service with enhanced monitoring
        # Note: ServiceManager creates system-wide instance; user-specific instances created via dependency injection
        self.factor_intelligence_service = FactorIntelligenceService(cache_results)
        
        # Update async service if enabled
        if enable_async:
            from services.async_service import AsyncPortfolioService
            self.async_service = AsyncPortfolioService()
            # TODO: Add AsyncFactorIntelligenceService when implemented
        else:
            self.async_service = None
    
    @log_error_handling("medium")
    @log_portfolio_operation_decorator("service_manager_health_check")
    @log_performance(0.5)
    def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check including Factor Intelligence."""
        health_status = {
            'portfolio_service': self.portfolio_service.health_check(),
            'optimization_service': self.optimization_service.health_check(),
            'stock_service': self.stock_service.health_check(),
            'scenario_service': self.scenario_service.health_check(),
            'factor_intelligence_service': self.factor_intelligence_service.health_check(),
            'cache_enabled': self.cache_results,
            'system_status': 'healthy'
        }
        
        # Determine overall system health
        unhealthy_services = [
            service for service, status in health_status.items() 
            if isinstance(status, dict) and status.get('status') != 'healthy'
        ]
        
        if unhealthy_services:
            health_status['system_status'] = 'degraded'
            health_status['unhealthy_services'] = unhealthy_services
            
            log_service_health("service_manager", "degraded", None, {
                "unhealthy_services": unhealthy_services
            })
        else:
            log_service_health("service_manager", "healthy", 0.1)
        
        return health_status
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Comprehensive cache statistics including Factor Intelligence."""
        return {
            'portfolio_service': self.portfolio_service.get_cache_stats(),
            'optimization_service': self.optimization_service.get_cache_stats(),
            'stock_service': self.stock_service.get_cache_stats(),
            'scenario_service': self.scenario_service.get_cache_stats(),
            'factor_intelligence_service': self.factor_intelligence_service.get_cache_stats(),
            'system_cache_summary': {
                'total_services': 5,
                'cache_enabled': self.cache_results
            }
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Comprehensive performance statistics including Factor Intelligence."""
        return {
            'portfolio_service': getattr(self.portfolio_service, 'get_performance_stats', lambda: {})(),
            'factor_intelligence_service': self.factor_intelligence_service.get_performance_stats(),
            'system_performance_summary': {
                'services_monitored': 2,  # Services with performance tracking
                'monitoring_enabled': True
            }
        }
    
    def get_available_functions(self) -> Dict[str, list]:
        """Updated function registry including Factor Intelligence."""
        functions = {
            'portfolio_service': [
                'analyze_portfolio',
                'analyze_risk_score', 
                'analyze_performance'
            ],
            'optimization_service': [
                'optimize_minimum_variance',
                'optimize_maximum_return'
            ],
            'stock_service': [
                'analyze_stock'
            ],
            'scenario_service': [
                'analyze_what_if',
                'analyze_delta_scenario',
                'analyze_stress_scenario'
            ],
            'factor_intelligence_service': [
                'analyze_factor_correlations',
                'analyze_factor_performance', 
                'generate_offset_recommendations',
                'create_factor_group',
                'get_factor_group',
                'list_factor_groups',
                'delete_factor_group'
            ]
        }
        
        if self.enable_async:
            functions['async_service'] = [
                'analyze_portfolio_async',
                'analyze_risk_score_async',
                'analyze_performance_async',
                'analyze_multiple_portfolios',
                'analyze_portfolio_with_progress',
                'analyze_what_if_async',
                'optimize_portfolio_async',
                'analyze_stock_async',
                'batch_analyze_stocks',
                'comprehensive_analysis_async'
            ]
        
        return functions
    
    def get_service(self, service_name: str):
        """Get a specific service by name - updated with factor intelligence"""
        services = {
            'portfolio': self.portfolio_service,
            'optimization': self.optimization_service,
            'stock': self.stock_service,
            'scenario': self.scenario_service,
            'security_type': self.security_type_service,
            'factor_intelligence': self.factor_intelligence_service,  # New service
        }
        
        if self.enable_async:
            services['async'] = self.async_service
        
        if service_name not in services:
            available_services = list(services.keys())
            raise ServiceError(f"Unknown service: {service_name}. Available services: {available_services}")
        
        return services[service_name]
    
    def clear_all_caches(self):
        """Clear all service caches including factor intelligence"""
        self.portfolio_service.clear_cache()
        self.optimization_service.clear_cache()
        self.stock_service.clear_cache()
        self.scenario_service.clear_cache()
        self.factor_intelligence_service.clear_cache()  # New cache clearing
        
        # Note: Async service uses the same underlying services,
        # so their caches are already cleared above
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for all services including factor intelligence"""
        return {
            'portfolio_service': self.portfolio_service.get_cache_stats(),
            'optimization_service': self.optimization_service.get_cache_stats(),
            'stock_service': self.stock_service.get_cache_stats(),
            'scenario_service': self.scenario_service.get_cache_stats(),
            'factor_intelligence_service': self.factor_intelligence_service.get_cache_stats(),  # New stats
        }
```

### **4. 🗄️ Database Migration: `/database/migrations/20250903_add_factor_intelligence.sql`**

```sql
-- ============================================================================
-- FACTOR INTELLIGENCE ENGINE DATABASE MIGRATION
-- ============================================================================
-- Migration: 20250903_add_factor_intelligence.sql
-- Purpose: Add support for user-defined factor groups and factor intelligence
-- 
-- Features Added:
-- - User-defined factor groups with flexible weighting
-- - Market-cap, equal, and custom weighting support
-- - User isolation and data integrity constraints
-- - Performance optimized indexing
-- 
-- Safe to run multiple times (uses IF NOT EXISTS)
-- ============================================================================

-- Add user-defined factor groups table
CREATE TABLE IF NOT EXISTS user_factor_groups (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_name VARCHAR(100) NOT NULL,
    description TEXT,
    tickers JSONB NOT NULL,                     -- Array of ticker symbols
    weights JSONB,                              -- Optional custom weights dict
    weighting_method VARCHAR(20) DEFAULT 'equal' CHECK (weighting_method IN ('equal', 'market_cap', 'custom')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Ensure unique group names per user
    UNIQUE(user_id, group_name),
    
    -- Validate JSONB structure
    CONSTRAINT valid_tickers CHECK (jsonb_typeof(tickers) = 'array'),
    CONSTRAINT valid_weights CHECK (weights IS NULL OR jsonb_typeof(weights) = 'object')
);

-- Performance indexes for factor groups
CREATE INDEX IF NOT EXISTS idx_user_factor_groups_user_id ON user_factor_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_user_factor_groups_created_at ON user_factor_groups(created_at);
CREATE INDEX IF NOT EXISTS idx_user_factor_groups_weighting_method ON user_factor_groups(weighting_method);

-- Add optional reference to user factor groups in existing factor_proxies table
-- This allows linking standard factor proxies to user-defined groups when needed
ALTER TABLE factor_proxies 
ADD COLUMN IF NOT EXISTS user_factor_group_id INT REFERENCES user_factor_groups(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_factor_proxies_user_factor_group ON factor_proxies(user_factor_group_id) 
WHERE user_factor_group_id IS NOT NULL;

-- Add trigger to update updated_at timestamp on factor group changes
CREATE OR REPLACE FUNCTION update_factor_group_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER IF NOT EXISTS trigger_update_factor_group_updated_at
    BEFORE UPDATE ON user_factor_groups
    FOR EACH ROW
    EXECUTE FUNCTION update_factor_group_updated_at();

-- Verify migration success
DO $$
BEGIN
    -- Check if table was created successfully
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_factor_groups') THEN
        RAISE NOTICE 'Factor Intelligence migration completed successfully';
        RAISE NOTICE 'Table user_factor_groups created with % indexes', 
            (SELECT count(*) FROM pg_indexes WHERE tablename = 'user_factor_groups');
    ELSE
        RAISE EXCEPTION 'Factor Intelligence migration failed - table not created';
    END IF;
END $$;

-- Sample data for testing (optional - remove in production)
-- INSERT INTO user_factor_groups (user_id, group_name, description, tickers, weighting_method)
-- VALUES 
--     (1, 'Tech Giants', 'Large-cap technology stocks', '["AAPL", "MSFT", "GOOGL", "AMZN"]', 'market_cap'),
--     (1, 'Dividend Aristocrats', 'High-dividend stable stocks', '["JNJ", "PG", "KO", "PEP"]', 'equal');
```

### **5. 📱 Frontend Integration Points**

Following your established frontend architecture patterns with modular services:


#### **Factor Intelligence Service Class**

```typescript
// /frontend/src/chassis/services/FactorIntelligenceService.ts
/**
 * ✅ CRITICAL INFRASTRUCTURE - FACTOR INTELLIGENCE SERVICE
 * 
 * FactorIntelligenceService - Factor analysis and market intelligence API client
 * 
 * USAGE LOCATIONS:
 * - FactorIntelligenceManager.ts - Factor analysis business logic operations
 * - Factor Intelligence hooks - Via SessionServicesProvider and useSessionServices()
 * - Factor Intelligence components - Through manager and adapter layers
 * 
 * FUNCTIONS:
 * - Factor correlation matrix analysis
 * - Factor performance profiling
 * - Portfolio-aware offset recommendations
 * - User-defined factor group management
 * - Market intelligence data retrieval
 * 
 * ARCHITECTURE ROLE:
 * Specialized service for factor intelligence operations following the established
 * modular service pattern. Integrates with APIService request infrastructure
 * and provides factor-specific business logic coordination.
 */

import { frontendLogger } from '../../services/frontendLogger';
import { 
  FactorCorrelationApiResponse,
  FactorPerformanceApiResponse,
  OffsetRecommendationApiResponse,
  FactorGroupListApiResponse,
  FactorGroupApiResponse
} from '../../types/api';

export interface FactorIntelligenceServiceOptions {
  baseURL: string;
  request: <T>(endpoint: string, options?: RequestInit) => Promise<T>;
}

/**
 * Factor Intelligence service for market analysis and offset recommendations.
 * Follows established service architecture patterns.
 */
export class FactorIntelligenceService {
  private baseURL: string;
  private request: <T>(endpoint: string, options?: RequestInit) => Promise<T>;

  constructor(options: FactorIntelligenceServiceOptions) {
    this.baseURL = options.baseURL;
    this.request = options.request;
  }

  // Core service methods following established patterns...
  async analyzeFactorCorrelations(request: FactorCorrelationRequest = {}): Promise<FactorCorrelationApiResponse> {
    // Implementation following RiskAnalysisService patterns
  }

  async generateOffsetRecommendations(request: OffsetRecommendationRequest): Promise<OffsetRecommendationApiResponse> {
    // Implementation following established service patterns
  }

  // Additional methods...
}
```

#### **Manager Layer Integration**

```typescript
// /frontend/src/chassis/managers/FactorIntelligenceManager.ts
/**
 * ✅ CRITICAL INFRASTRUCTURE - CROSS-UI MANAGER
 * 
 * Factor Intelligence Manager - Comprehensive factor analysis workflow coordinator
 * 
 * USAGE LOCATIONS:
 * - SessionServicesProvider.tsx - Creates and provides FactorIntelligenceManager instances
 * - useFactorIntelligenceManager() hook - Provides access to manager for components
 * - Serves BOTH Legacy and Modern UI through shared session services
 * 
 * FUNCTIONS:
 * - Factor correlation matrix analysis coordination
 * - Factor performance profiling workflows
 * - Portfolio-aware offset recommendation generation
 * - User-defined factor group management
 * - Multi-service coordination for market intelligence
 * 
 * ARCHITECTURE ROLE:
 * ==================
 * Core business logic coordinator that orchestrates factor intelligence operations,
 * market analysis, and portfolio-aware recommendations. Acts as the central hub
 * for all factor-related operations in the application.
 * 
 * KEY RESPONSIBILITIES:
 * ====================
 * • Factor Analysis: Correlation matrices, performance profiles, market intelligence
 * • Offset Recommendations: Portfolio-aware hedging suggestions and risk mitigation
 * • Factor Group Management: User-defined factor creation and validation
 * • Cache Coordination: Intelligent caching for expensive factor analysis operations
 * • State Management: Thread-safe updates with race condition protection
 * • Service Integration: Coordination between APIService and FactorIntelligenceService
 */

import { APIService } from '../services/APIService';
import { FactorIntelligenceService } from '../services/FactorIntelligenceService';
import { PortfolioCacheService } from '../services/PortfolioCacheService';
import { frontendLogger } from '../../services/frontendLogger';

export class FactorIntelligenceManager {
  private apiService: APIService;
  private factorIntelligenceService: FactorIntelligenceService;
  private portfolioCacheService: PortfolioCacheService;
  
  // Per-task locking to prevent concurrent updates
  private updateFlags = {
    correlationAnalysis: false,
    performanceAnalysis: false,
    offsetRecommendations: false,
    factorGroupManagement: false
  };

  constructor(
    apiService: APIService,
    factorIntelligenceService: FactorIntelligenceService,
    portfolioCacheService: PortfolioCacheService
  ) {
    this.apiService = apiService;
    this.factorIntelligenceService = factorIntelligenceService;
    this.portfolioCacheService = portfolioCacheService;
  }

  /**
   * Analyze factor correlations with caching and error handling
   * @param portfolioId - Portfolio context for analysis
   * @param options - Analysis options (date range, max factors, etc.)
   * @returns Factor correlation analysis results
   */
  async analyzeFactorCorrelations(portfolioId: string, options: FactorCorrelationRequest = {}) {
    if (this.updateFlags.correlationAnalysis) {
      return { data: null, error: 'Factor correlation analysis already in progress' };
    }

    this.updateFlags.correlationAnalysis = true;
    
    try {
      frontendLogger.logManager('FactorIntelligenceManager', 'Starting factor correlation analysis', {
        portfolioId,
        options
      });

      const result = await this.factorIntelligenceService.analyzeFactorCorrelations(options);
      
      frontendLogger.logManager('FactorIntelligenceManager', 'Factor correlation analysis completed', {
        portfolioId,
        factorsAnalyzed: result.data_quality?.factors_analyzed,
        success: result.success
      });

      return { data: result, error: null };
    } catch (error) {
      frontendLogger.logManager('FactorIntelligenceManager', 'Factor correlation analysis failed', {
        portfolioId,
        error: error instanceof Error ? error.message : 'Unknown error'
      });
      return { data: null, error: error instanceof Error ? error.message : 'Analysis failed' };
    } finally {
      this.updateFlags.correlationAnalysis = false;
    }
  }

  /**
   * Generate portfolio-aware offset recommendations
   * @param portfolioId - Portfolio to analyze for recommendations
   * @param overexposedFactor - Factor that is overexposed
   * @param options - Recommendation options
   * @returns Offset recommendation results
   */
  async generateOffsetRecommendations(
    portfolioId: string, 
    overexposedFactor: string, 
    options: Partial<OffsetRecommendationRequest> = {}
  ) {
    if (this.updateFlags.offsetRecommendations) {
      return { data: null, error: 'Offset recommendation generation already in progress' };
    }

    this.updateFlags.offsetRecommendations = true;
    
    try {
      frontendLogger.logManager('FactorIntelligenceManager', 'Starting offset recommendation generation', {
        portfolioId,
        overexposedFactor,
        options
      });

      const request: OffsetRecommendationRequest = {
        portfolio_name: portfolioId,
        overexposed_factor: overexposedFactor,
        ...options
      };

      const result = await this.factorIntelligenceService.generateOffsetRecommendations(request);
      
      frontendLogger.logManager('FactorIntelligenceManager', 'Offset recommendations generated', {
        portfolioId,
        overexposedFactor,
        recommendationCount: result.recommendations?.length,
        success: result.success
      });

      return { data: result, error: null };
    } catch (error) {
      frontendLogger.logManager('FactorIntelligenceManager', 'Offset recommendation generation failed', {
        portfolioId,
        overexposedFactor,
        error: error instanceof Error ? error.message : 'Unknown error'
      });
      return { data: null, error: error instanceof Error ? error.message : 'Recommendation generation failed' };
    } finally {
      this.updateFlags.offsetRecommendations = false;
    }
  }

  // Additional manager methods following established patterns...
}
```

#### **Adapter Layer Integration**

```typescript
// /frontend/src/adapters/FactorCorrelationAdapter.ts
/**
 * FactorCorrelationAdapter - Transforms factor correlation API responses into dashboard-ready format
 * 
 * COORDINATED CACHING ARCHITECTURE INTEGRATION:
 * ============================================
 * This adapter follows the coordinated caching system, providing unified cache management
 * and event-driven invalidation across all cache layers, following the RiskScoreAdapter pattern.
 * 
 * BACKEND ENDPOINT INTEGRATION:
 * - Source Endpoint: POST /api/factor-intelligence/correlations
 * - Dedicated Endpoint: Factor correlation matrix analysis
 * - API Request: { start_date?, end_date?, max_factors?, factor_universe? }
 * - Response Cache: Multi-layer caching via coordinated caching system
 * 
 * INPUT DATA STRUCTURE (from Backend API Response):
 * {
 *   success: boolean,
 *   correlation_matrix: Record<string, Record<string, number>>,
 *   data_quality: {
 *     factors_analyzed: number,
 *     factors_excluded: number,
 *     excluded_factor_list: string[],
 *     observations: number,
 *     data_coverage_pct: number
 *   },
 *   formatted_table: string,
 *   analysis_metadata: Record<string, any>
 * }
 * 
 * OUTPUT DATA STRUCTURE (Transformed for UI):
 * {
 *   correlation_matrix: Record<string, Record<string, number>>,
 *   factor_list: string[],
 *   strongest_correlations: Array<{
 *     factor1: string,
 *     factor2: string,
 *     correlation: number,
 *     strength: 'strong' | 'moderate' | 'weak'
 *   }>,
 *   data_quality: {
 *     factors_analyzed: number,
 *     factors_excluded: number,
 *     excluded_factors: string[],
 *     data_coverage_percent: number,
 *     quality_score: 'excellent' | 'good' | 'fair' | 'poor'
 *   },
 *   formatted_table: string,
 *   analysis_metadata: Record<string, any>
 * }
 */

import { frontendLogger } from '../services/frontendLogger';
import { getCacheTTL } from '../utils/cacheConfig';
import type { UnifiedAdapterCache } from '../chassis/services/UnifiedAdapterCache';
import { generateStandardCacheKey, generateContentHash, type CacheKeyMetadata } from '../types/cache';

export class FactorCorrelationAdapter {
  private cache: Map<string, { data: any; timestamp: number }> = new Map();
  private get CACHE_TTL() { return getCacheTTL(); }
  
  constructor(private unifiedCache?: UnifiedAdapterCache, private contextPortfolioId?: string) {}

  /**
   * Transform factor correlation API response into UI-ready format
   * @param correlationData - Raw correlation data from API
   * @returns Transformed correlation data
   */
  transform(correlationData: any) {
    const cacheKey = this.generateCacheKey(correlationData);
    
    if (this.unifiedCache) {
      return this.unifiedCache.get(
        cacheKey,
        () => this.performTransformation(correlationData),
        this.CACHE_TTL,
        { portfolioId: this.contextPortfolioId || 'unknown', dataType: 'factorCorrelation' }
      );
    } else {
      if (this.isValidCache(cacheKey)) {
        frontendLogger.state.cacheHit('FactorCorrelationAdapter', cacheKey);
        return this.cache.get(cacheKey)!.data;
      }
      
      return this.performTransformation(correlationData, cacheKey);
    }
  }

  private performTransformation(correlationData: any, cacheKey?: string) {
    frontendLogger.adapter.transformStart('FactorCorrelationAdapter', correlationData);
    
    try {
      const correlationMatrix = correlationData.correlation_matrix || {};
      const factorList = Object.keys(correlationMatrix);
      
      // Extract strongest correlations for highlighting
      const strongestCorrelations = this.extractStrongestCorrelations(correlationMatrix);
      
      // Assess data quality
      const dataQuality = this.assessDataQuality(correlationData.data_quality || {});
      
      const transformedData = {
        correlation_matrix: correlationMatrix,
        factor_list: factorList,
        strongest_correlations: strongestCorrelations,
        data_quality: dataQuality,
        formatted_table: correlationData.formatted_table || '',
        analysis_metadata: correlationData.analysis_metadata || {}
      };

      frontendLogger.adapter.transformSuccess('FactorCorrelationAdapter', {
        factorCount: factorList.length,
        strongCorrelationsCount: strongestCorrelations.length,
        dataQuality: dataQuality.quality_score
      });

      if (cacheKey && !this.unifiedCache) {
        this.cache.set(cacheKey, {
          data: transformedData,
          timestamp: Date.now()
        });
      }

      return transformedData;
    } catch (error) {
      frontendLogger.adapter.transformError('FactorCorrelationAdapter', error as Error);
      throw new Error(`Factor correlation transformation failed: ${error}`);
    }
  }

  private extractStrongestCorrelations(matrix: Record<string, Record<string, number>>) {
    const correlations = [];
    const factors = Object.keys(matrix);
    
    for (let i = 0; i < factors.length; i++) {
      for (let j = i + 1; j < factors.length; j++) {
        const factor1 = factors[i];
        const factor2 = factors[j];
        const correlation = matrix[factor1]?.[factor2] || 0;
        
        if (Math.abs(correlation) > 0.3) { // Only significant correlations
          correlations.push({
            factor1,
            factor2,
            correlation,
            strength: Math.abs(correlation) > 0.7 ? 'strong' : 
                     Math.abs(correlation) > 0.5 ? 'moderate' : 'weak'
          });
        }
      }
    }
    
    return correlations.sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation));
  }

  private assessDataQuality(dataQuality: any) {
    const coverage = dataQuality.data_coverage_pct || 0;
    const factorsAnalyzed = dataQuality.factors_analyzed || 0;
    const factorsExcluded = dataQuality.factors_excluded || 0;
    
    let qualityScore: 'excellent' | 'good' | 'fair' | 'poor';
    if (coverage >= 90 && factorsExcluded < 2) qualityScore = 'excellent';
    else if (coverage >= 75 && factorsExcluded < 5) qualityScore = 'good';
    else if (coverage >= 60) qualityScore = 'fair';
    else qualityScore = 'poor';
    
    return {
      factors_analyzed: factorsAnalyzed,
      factors_excluded: factorsExcluded,
      excluded_factors: dataQuality.excluded_factor_list || [],
      data_coverage_percent: coverage,
      quality_score: qualityScore
    };
  }

  private generateCacheKey(correlationData: any): string {
    const content = {
      matrix_size: Object.keys(correlationData.correlation_matrix || {}).length,
      data_quality: correlationData.data_quality,
      analysis_date: correlationData.analysis_metadata?.analysis_date
    };
    
    const baseKey = generateContentHash(content);
    const metadata: CacheKeyMetadata = {
      portfolioId: this.contextPortfolioId || 'unknown',
      dataType: 'factorCorrelation',
      version: 'v1'
    };
    
    return generateStandardCacheKey(baseKey, metadata).key;
  }

  private isValidCache(key: string): boolean {
    const cached = this.cache.get(key);
    if (!cached) return false;
    return Date.now() - cached.timestamp <= this.CACHE_TTL;
  }

  clearCache(): void {
    if (this.unifiedCache) {
      this.unifiedCache.clearByType('factorCorrelation');
    } else {
      this.cache.clear();
    }
    frontendLogger.logComponent('FactorCorrelationAdapter', 'Factor correlation cache cleared');
  }
}
```

#### **Hooks Layer Integration**

```typescript
// /frontend/src/features/factorIntelligence/hooks/useFactorCorrelations.ts
/**
 * useFactorCorrelations - React hook for factor correlation matrix analysis
 * 
 * COORDINATED CACHING ARCHITECTURE INTEGRATION:
 * ============================================
 * This hook demonstrates the coordinated caching system in action, following
 * the same patterns as useRiskScore and usePerformance hooks.
 * 
 * DATA FLOW ARCHITECTURE:
 * Frontend Hook → SessionManager → FactorIntelligenceService → Backend API → FactorCorrelationAdapter → UI Components
 * 
 * BACKEND ENDPOINT INTEGRATION:
 * - Manager Method: manager.analyzeFactorCorrelations(portfolioId, options)
 * - Backend Endpoint: POST /api/factor-intelligence/correlations (via FactorIntelligenceService)
 * - Cache Strategy: HOOK_QUERY_CONFIG.useFactorCorrelations.staleTime + TanStack Query
 * - API Response: FactorCorrelationApiResponse (generated types)
 * 
 * ADAPTER TRANSFORMATION PIPELINE:
 * 1. Raw API Response → manager.analyzeFactorCorrelations() → correlationResult
 * 2. correlationResult → FactorCorrelationAdapter.transform() → Structured UI Data
 * 3. Structured Data → TanStack Query Cache → React Component State
 * 
 * OUTPUT DATA STRUCTURE (from FactorCorrelationAdapter.transform()):
 * {
 *   correlation_matrix: Record<string, Record<string, number>>,
 *   factor_list: string[],
 *   strongest_correlations: Array<{
 *     factor1: string, factor2: string, correlation: number, strength: string
 *   }>,
 *   data_quality: {
 *     factors_analyzed: number, quality_score: string, data_coverage_percent: number
 *   },
 *   formatted_table: string,
 *   analysis_metadata: Record<string, any>
 * }
 * 
 * DEPENDENCY CHAIN:
 * - Portfolio Store: useCurrentPortfolio() → Triggers refetch when portfolio changes
 * - Session Services: useSessionServices() → Provides manager instance for API calls
 * - Adapter Registry: Portfolio-scoped FactorCorrelationAdapter instance with caching
 * 
 * CACHING BEHAVIOR:
 * - TanStack Query: HOOK_QUERY_CONFIG.useFactorCorrelations.staleTime (frontend cache)
 * - FactorCorrelationAdapter: 30-minute internal cache (adapter-level cache)
 * - FactorIntelligenceService: Backend result caching (service-level cache)
 * - Query Key: factorCorrelationsKey(portfolioId, options) - invalidates when portfolio changes
 * 
 * ERROR HANDLING:
 * - API Errors: Thrown from manager methods → TanStack Query error state
 * - Adapter Errors: Thrown from adapter.transform() → Query error
 * - Validation Errors: No retry (failureCount check)
 * - Network Errors: Max 2 retries before failing
 * - No Portfolio: Returns null data (no API call made)
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useCurrentPortfolio } from '../../portfolio/hooks/useCurrentPortfolio';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import { frontendLogger } from '../../../services/frontendLogger';
import { HOOK_QUERY_CONFIG } from '../../../utils/queryConfig';

export interface FactorCorrelationOptions {
  start_date?: string;
  end_date?: string;
  max_factors?: number;
  factor_universe?: Record<string, string>;
  asset_class_filters?: { include?: string[]; exclude?: string[] };
  factor_categories?: string[]; // ['industry','style','market']
}

export const useFactorCorrelations = (options: FactorCorrelationOptions = {}) => {
  const { currentPortfolio } = useCurrentPortfolio();
  const { factorIntelligenceManager, factorCorrelationAdapter } = useSessionServices();
  const [analysisOptions, setAnalysisOptions] = useState<FactorCorrelationOptions>(options);

  const factorCorrelationsQuery = useQuery({
    queryKey: ['factorCorrelations', currentPortfolio?.id, analysisOptions],
    queryFn: async () => {
      if (!currentPortfolio?.id || !factorIntelligenceManager || !factorCorrelationAdapter) {
        return null;
      }

      frontendLogger.logHook('useFactorCorrelations', 'Starting factor correlation analysis', {
        portfolioId: currentPortfolio.id,
        options: analysisOptions
      });

      const result = await factorIntelligenceManager.analyzeFactorCorrelations(
        currentPortfolio.id,
        analysisOptions
      );

      if (result.error) {
        throw new Error(result.error);
      }

      if (!result.data) {
        throw new Error('No correlation data received');
      }

      // Transform through adapter
      const transformedData = factorCorrelationAdapter.transform(result.data);

      frontendLogger.logHook('useFactorCorrelations', 'Factor correlation analysis completed', {
        portfolioId: currentPortfolio.id,
        factorCount: transformedData.factor_list?.length,
        dataQuality: transformedData.data_quality?.quality_score
      });

      return transformedData;
    },
    enabled: !!currentPortfolio?.id && !!factorIntelligenceManager && !!factorCorrelationAdapter,
    staleTime: HOOK_QUERY_CONFIG.useFactorCorrelations?.staleTime || 5 * 60 * 1000, // 5 minutes
    retry: (failureCount, error: any) => {
      // Don't retry client errors (4xx) or rate limits (429)
      if (error?.status >= 400 && error?.status < 500) return false;
      if (error?.status === 429) return false;
      
      // Retry server errors up to 2 times
      return failureCount < 2;
    }
  });

  const updateAnalysisOptions = (newOptions: Partial<FactorCorrelationOptions>) => {
    setAnalysisOptions(prev => ({ ...prev, ...newOptions }));
  };

  return {
    // Data
    data: factorCorrelationsQuery.data,
    correlationMatrix: factorCorrelationsQuery.data?.correlation_matrix,
    factorList: factorCorrelationsQuery.data?.factor_list,
    strongestCorrelations: factorCorrelationsQuery.data?.strongest_correlations,
    dataQuality: factorCorrelationsQuery.data?.data_quality,
    formattedTable: factorCorrelationsQuery.data?.formatted_table,
    
    // State
    isLoading: factorCorrelationsQuery.isLoading,
    isRefetching: factorCorrelationsQuery.isRefetching,
    error: factorCorrelationsQuery.error?.message || null,
    
    // Computed state
    hasData: !!factorCorrelationsQuery.data,
    hasError: !!factorCorrelationsQuery.error,
    hasPortfolio: !!currentPortfolio,
    
    // Actions
    refetch: factorCorrelationsQuery.refetch,
    updateOptions: updateAnalysisOptions,
    
    // Options
    analysisOptions,
    currentPortfolio,
    
    // Legacy aliases (for backward compatibility)
    loading: factorCorrelationsQuery.isLoading,
    refreshCorrelations: factorCorrelationsQuery.refetch
  };
};

// === TYPE DEFINITIONS ===

export interface FactorCorrelationRequest {
  start_date?: string;
  end_date?: string;
  factor_universe?: Record<string, string>;
  max_factors?: number;
  asset_class_filters?: { include?: string[]; exclude?: string[] };
  factor_categories?: string[]; // e.g., ['industry','style','market','fixed_income','cash','commodity','crypto','rate']
  include_rate_sensitivity?: boolean;
  rate_maturities?: string[];
  // Macro-only cross-asset views are provided via macro_composite_matrix and macro_etf_matrix
  include_market_sensitivity?: boolean;
  market_benchmarks?: string[]; // e.g., ['SPY','ACWX','EEM']
  market_sensitivity_categories?: string[]; // defaults to ['industry','style'] if omitted
  include_macro_composite?: boolean;
  include_macro_etf?: boolean;
  macro_groups?: string[]; // e.g., ['equity','bond','cash','commodity','crypto']
  macro_max_per_group?: number; // e.g., 5
  macro_deduplicate_threshold?: number; // e.g., 0.95
  macro_min_group_coverage_pct?: number; // falls back to settings when omitted
  rate_sensitivity_categories?: string[]; // defaults to ['fixed_income','industry','market','cash'] if omitted
  // Output/customization controls
  sections?: string[]; // e.g., ['matrices:industry','overlays:rate','macro:composite']
  format?: 'json' | 'table' | 'both'; // default 'json'
  top_n_per_matrix?: number; // default 15
  // Industry granularity controls
  industry_granularity?: 'group' | 'industry' | 'subindustry'; // default 'group'
  industry_group_source?: 'sector_etf' | 'bucket_file'; // default 'sector_etf'
  // Rolling/stability and regime (future)
  include_rolling_summaries?: boolean; // default false
  rolling_windows?: number[]; // e.g., [12,24,36]
  regime?: string | null; // reserved for future regime classifier
}

export interface FactorPerformanceRequest {
  start_date?: string;
  end_date?: string;
  benchmark_ticker?: string;
  factor_universe?: Record<string, string>;
  asset_class_filters?: { include?: string[]; exclude?: string[] };
  factor_categories?: string[];
  // Note: no rate betas in factor intelligence performance
  include_macro_composite_performance?: boolean; // default true
  include_factor_composite_performance?: boolean; // default true
  composite_weighting_method?: 'equal' | 'cap' | 'custom'; // default 'equal'
  composite_max_per_group?: number; // optional cap
}

export interface OffsetRecommendationRequest {
  portfolio_name?: string;
  overexposed_factor: string;
  target_allocation_reduction?: number;
  correlation_threshold?: number;
  asset_class_filters?: { include?: string[]; exclude?: string[] };
  prefer_income?: boolean;
  min_dividend_yield?: number; // 0.00 - 1.00
  factor_categories?: string[];
}


## Post‑Implementation Considerations (Parking Lot)

The core design is ready. Below are pragmatic enhancements and guardrails to consider after initial implementation. These are not in scope now but serve as a checklist for future hardening.

- Universe hygiene and quality
  - De‑duplication: Drop or coalesce near‑duplicate ETFs (|corr| ≥ 0.95 within a group) with a rule (prefer higher ADV/lower fee).
  - Liquidity/fees: Optional screens/penalties to keep matrices practical and recommendations investable.
  - Survivorship bias: Minimal versioning/audit for `asset_etf_proxies` updates.

- Stability and regimes
  - Rolling windows: Optional 12/24/36m correlation summaries (or stability score) to avoid over‑fitting a single window.
  - Stress slicing: Optional “large Δy move” subsets to surface behavior in rate shocks.

- Composite methodology
  - Weighting: Equal‑weight default; cap‑weight/custom require data sources and a reconstitution cadence (e.g., quarterly). Document cadence.
  - Inclusion rules: Cap constituents per composite; log exclusions/coverage.

- Yield nuances
  - Bond yields: TTM distribution vs SEC yield; stick with current yield for consistency but consider optional SEC yield column if available.
  - Cash ETFs: Confirm TR series capture distributions; align monthly accrual with yield reporting.

- Currency and benchmarks
  - Currency effects: Note USD base; if local‑currency assets appear later, document conversion policy.
  - Benchmarks: Avoid self‑correlation (skip ETFs used as benchmarks); allow discovery via exchange map when user omits benchmarks.

- Caching and cost control
  - Returns panel cache: Cache aligned monthly panel per (universe_hash, start, end) and share across sections.
  - Heavy sections opt‑in: Keep macro ETF matrix opt‑in; enforce `macro_max_per_group` and time budgets; return partials with notes.

- API ergonomics and payload size
  - Table caps: `top_n_per_matrix` defaults conservatively; consistent across renderers.
  - Large payloads: Support `format='table'` to avoid giant JSON matrices for AI/CLI; consider trimming rarely‑used fields when not requested.

- Admin and governance
  - `asset_etf_proxies` audit: Consider updated_by/updated_reason; simple history if frequent edits expected.
  - Sync safety: DB↔YAML sync never silently deletes; require `--force` for removals.

- Defaults and presets
  - Provide preset views (overview, equity_factors, macro_focus, income_focus, light) mapped to `sections` + options.
  - Label clearly: “sensitivity = correlation overlay” vs “beta in profiles”.

- Testing
  - Golden snapshots for a fixed universe/window (per‑category matrices, macro composites, overlays, sample profiles).
  - Property tests: correlations in [-1,1], symmetry for square matrices, stable behavior with missing data.
  - Performance tests: 200+ factors ceiling; verify cache effectiveness.

- Error handling and fallbacks
  - Partial success: Return available sections with explicit `data_quality` reasons for skipped parts (timeouts, data gaps).
  - Provider outage: Log which tier (DB/YAML/hardcoded) was used per section in `analysis_metadata`.

- Documentation polish
  - Add “Top Insights” summaries (e.g., strongest diversifier vs SPY; most negative corr to UST10Y among equities).
  - Small glossary: category, asset_class, sensitivity vs beta, macro composites, etc.

export interface CreateFactorGroupRequest {
  group_name: string;
  description?: string;
  tickers: string[];
  weights?: Record<string, number>;
  weighting_method?: 'equal' | 'market_cap' | 'custom';
}

export interface FactorGroup {
  group_name: string;
  description?: string;
  tickers: string[];
  weighting_method: string;
  created_at: string;
  updated_at?: string;
  is_valid: boolean;
  ticker_count: number;
}

export interface FactorCorrelationResponse {
  success: boolean;
  correlation_matrix: Record<string, Record<string, number>>;
  data_quality: {
    factors_analyzed: number;
    factors_excluded: number;
    excluded_factor_list: string[];
    observations: number;
    data_coverage_pct: number;
  };
  formatted_table: string;
  analysis_metadata: Record<string, any>;
}

export interface OffsetRecommendation {
  factor: string;
  etf_ticker: string;
  correlation_to_overexposed: number;
  current_portfolio_exposure: number;
  suggested_additional_allocation: number;
  sharpe_ratio: number;
  max_drawdown: number;
  rationale: string;
}


```

#### **Modern UI Component Integration**

```tsx
// /frontend/src/components/dashboard/views/modern/FactorIntelligenceContainer.tsx
/**
 * FactorIntelligenceContainer - Container component for modern Factor Intelligence views
 * 
 * COORDINATED CACHING ARCHITECTURE INTEGRATION:
 * ============================================
 * This container follows the coordinated caching system, providing unified cache management
 * and event-driven invalidation across all cache layers, following established patterns.
 * 
 * Data Flow Architecture:
 * Hook: useFactorCorrelations() from ../../../../features/factorIntelligence/hooks/useFactorCorrelations.ts
 * ├── Manager: FactorIntelligenceManager.analyzeFactorCorrelations(portfolioId, options)
 * ├── Adapter: FactorCorrelationAdapter.transform(correlationResult) [with UnifiedAdapterCache]
 * └── Query: TanStack Query with coordinated cache + event-driven invalidation
 * 
 * Data Structure (from FactorCorrelationAdapter.transform):
 * {
 *   correlation_matrix: Record<string, Record<string, number>>,
 *   factor_list: string[],
 *   strongest_correlations: Array<{
 *     factor1: string, factor2: string, correlation: number, strength: string
 *   }>,
 *   data_quality: {
 *     factors_analyzed: number, quality_score: string, data_coverage_percent: number
 *   },
 *   formatted_table: string,
 *   analysis_metadata: Record<string, any>
 * }
 * 
 * Props Passed to FactorIntelligenceView:
 * - data: Transformed data object from FactorCorrelationAdapter
 * - onRefresh: () => void - Function to refresh factor analysis data
 * - onRecommendationRequest: (factor: string) => void - Function to request offset recommendations
 * - loading: boolean - TanStack Query loading state
 * - className: string - Optional CSS classes
 * 
 * State Management:
 * - Caching: Separate cache from portfolio data (factor-specific analysis)
 * - Error Handling: Automatic retry except for validation errors
 * - Portfolio Dependency: Auto-refetches when currentPortfolio changes
 * - Event Integration: Uses factor-intelligence cache invalidation events
 */

import React, { useEffect, useState } from 'react';
import { useFactorCorrelations } from '../../../../features/factorIntelligence/hooks/useFactorCorrelations';
import { useSessionServices } from '../../../../providers/SessionServicesProvider';
import { DashboardErrorBoundary, ErrorMessage, LoadingSpinner, NoDataMessage } from '../../shared';
import { frontendLogger } from '../../../../services/frontendLogger';
import FactorIntelligenceView from '../../../factorIntelligence/FactorIntelligenceView';
import { IntentRegistry } from '../../../../utils/NavigationIntents';

interface FactorIntelligenceContainerProps {
  className?: string;
  [key: string]: any;
}

const FactorIntelligenceContainer: React.FC<FactorIntelligenceContainerProps> = ({ ...props }) => {
  // Analysis options state
  const [analysisOptions, setAnalysisOptions] = useState({
    max_factors: 15,
    start_date: undefined,
    end_date: undefined
  });

  // Get EventBus for cache invalidation events
  const { eventBus } = useSessionServices();
  
  // useFactorCorrelations Hook (TanStack Query + FactorCorrelationAdapter)
  const { 
    data,                    // FactorCorrelationAdapter transformed data
    isLoading,               // TanStack Query isLoading state
    error,                   // Error message string from query failure
    hasData,                 // Boolean: !!data (true if adapter returned valid data)
    hasError,                // Boolean: !!error (true if any error occurred)
    hasPortfolio,            // Boolean: !!currentPortfolio (true if portfolio loaded)
    refetch,                 // Function: TanStack Query refetch() - triggers new API call
    updateOptions,           // Function: Update analysis options
    currentPortfolio         // Portfolio object from portfolioStore
  } = useFactorCorrelations(analysisOptions);
  
  // ✅ EVENT-DRIVEN UPDATES: Listen for cache invalidation events
  useEffect(() => {
    if (!eventBus || !currentPortfolio?.id) return;
    
    const handleFactorDataInvalidated = (event: any) => {
      if (event.portfolioId === currentPortfolio.id) {
        frontendLogger.user.action('cacheInvalidationReceived', 'FactorIntelligenceContainer', {
          eventType: 'factor-data-invalidated',
          portfolioId: event.portfolioId
        });
        refetch();
      }
    };
    
    const handleCacheUpdated = (event: any) => {
      if (event.portfolioId === currentPortfolio.id && 
          (event.dataType === 'factorCorrelation' || event.dataType === 'factorIntelligence')) {
        frontendLogger.user.action('cacheUpdateReceived', 'FactorIntelligenceContainer', {
          eventType: 'cache-updated',
          dataType: event.dataType,
          portfolioId: event.portfolioId
        });
      }
    };
    
    const unsubscribeFactorInvalidated = eventBus.on('factor-data-invalidated', handleFactorDataInvalidated);
    const unsubscribeCacheUpdated = eventBus.on('cache-updated', handleCacheUpdated);
    
    return () => {
      unsubscribeFactorInvalidated();
      unsubscribeCacheUpdated();
    };
  }, [eventBus, currentPortfolio?.id, refetch]);
  
  // Component lifecycle logging (same pattern as other containers)
  useEffect(() => {
    frontendLogger.user.action('viewRendered', 'FactorIntelligence', {
      hasData: !!data,
      isLoading: isLoading,
      hasError: !!error
    });
  }, [data, isLoading, error]);

  // Handle refresh with intent system integration
  const handleRefresh = async () => {
    try {
      const result = await IntentRegistry.triggerIntent('refresh-factor-intelligence');
      if (result.success) {
        await refetch();
      }
    } catch (intentError) {
      // Fallback to direct refetch if intent fails
      frontendLogger.info('Factor intelligence refresh intent not registered, using direct refetch', 'FactorIntelligenceContainer');
      await refetch();
    }
  };

  // Handle recommendation request
  const handleRecommendationRequest = async (overexposedFactor: string) => {
    try {
      const result = await IntentRegistry.triggerIntent('generate-offset-recommendations', {
        overexposed_factor: overexposedFactor,
        portfolio_id: currentPortfolio?.id
      });
      
      if (result.success) {
        frontendLogger.user.action('offset-recommendations-requested', 'FactorIntelligenceContainer', {
          overexposedFactor,
          portfolioId: currentPortfolio?.id
        });
      }
    } catch (error) {
      frontendLogger.error('Failed to request offset recommendations', 'FactorIntelligenceContainer', error as Error);
    }
  };

  // Handle analysis options update
  const handleOptionsUpdate = (newOptions: Partial<typeof analysisOptions>) => {
    const updatedOptions = { ...analysisOptions, ...newOptions };
    setAnalysisOptions(updatedOptions);
    updateOptions(updatedOptions);
  };

  // Show loading state (same pattern as other containers)
  if (isLoading) {
    return <LoadingSpinner message="Loading factor correlation analysis..." />;
  }

  // Show error state with retry (same pattern as other containers)
  if (error) {
    return (
      <ErrorMessage 
        error={error}
        onRetry={() => {
          refetch();
        }}
      />
    );
  }

  // Show no portfolio message (same pattern as other containers)
  if (!hasPortfolio) {
    return (
      <NoDataMessage 
        message="No portfolio loaded. Please upload a portfolio to view factor intelligence."
        actionLabel="Upload Portfolio"
        onAction={async () => {
          try {
            const result = await IntentRegistry.triggerIntent('navigate-to-portfolio-upload');
            if (result.success) {
              frontendLogger.user.action('navigate-to-portfolio-upload', 'FactorIntelligenceContainer');
            }
          } catch (intentError) {
            frontendLogger.user.action('navigate-to-portfolio-upload-fallback', 'FactorIntelligenceContainer');
          }
        }}
      />
    );
  }

  // Pass FactorCorrelationAdapter data to modern view component
  return (
    <DashboardErrorBoundary>
      <FactorIntelligenceView 
        data={data}                              // FactorCorrelationAdapter.transform() output
        onRefresh={handleRefresh}                // Function to trigger refresh via intent + refetch
        onRecommendationRequest={handleRecommendationRequest} // Function to request offset recommendations
        onOptionsUpdate={handleOptionsUpdate}    // Function to update analysis options
        analysisOptions={analysisOptions}        // Current analysis options
        loading={isLoading}                      // Loading state for internal component use
        className={props.className}              // Optional styling
        {...props}
      />
      
      {/* Development indicator (same pattern as other containers) */}
      {process.env.NODE_ENV === 'development' && (
        <div className="fixed bottom-4 right-4 bg-blue-100 text-blue-800 px-3 py-1 rounded text-xs">
          Factor Intelligence: {hasData ? 'Real' : 'Mock'} | Portfolio: {hasPortfolio ? 'Loaded' : 'None'}
        </div>
      )}
    </DashboardErrorBoundary>
  );
};

// ✅ SMART MEMOIZATION: Data-aware comparison to prevent unnecessary re-renders
const smartComparison = (prevProps: FactorIntelligenceContainerProps, nextProps: FactorIntelligenceContainerProps) => {
  return (
    prevProps.className === nextProps.className &&
    Object.keys(prevProps).length === Object.keys(nextProps).length
  );
};

export default React.memo(FactorIntelligenceContainer, smartComparison);
```

```tsx
// /frontend/src/components/factorIntelligence/FactorIntelligenceView.tsx
/**
 * FactorIntelligenceView - Modern UI component for factor correlation matrix display
 * 
 * This component follows the established modern UI patterns with:
 * - Shared UI components (Card, Button, etc.)
 * - Consistent styling and layout
 * - Interactive elements with proper event handling
 * - Data quality indicators
 * - Loading and error states handled by container
 */

import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { RefreshCw, Download, Info, TrendingUp, TrendingDown } from 'lucide-react';

interface FactorIntelligenceViewProps {
  data: {
    correlation_matrix: Record<string, Record<string, number>>;
    factor_list: string[];
    strongest_correlations: Array<{
      factor1: string;
      factor2: string;
      correlation: number;
      strength: 'strong' | 'moderate' | 'weak';
    }>;
    data_quality: {
      factors_analyzed: number;
      factors_excluded: number;
      excluded_factors: string[];
      data_coverage_percent: number;
      quality_score: 'excellent' | 'good' | 'fair' | 'poor';
    };
    formatted_table: string;
    analysis_metadata: Record<string, any>;
  } | null;
  onRefresh: () => void;
  onRecommendationRequest: (factor: string) => void;
  onOptionsUpdate: (options: any) => void;
  analysisOptions: {
    max_factors: number;
    start_date?: string;
    end_date?: string;
  };
  loading?: boolean;
  className?: string;
}

const FactorIntelligenceView: React.FC<FactorIntelligenceViewProps> = ({
  data,
  onRefresh,
  onRecommendationRequest,
  onOptionsUpdate,
  analysisOptions,
  loading = false,
  className = ''
}) => {
  if (!data) {
    return (
      <div className={`space-y-6 ${className}`}>
        <Card>
          <CardContent className="p-8 text-center">
            <p className="text-gray-500">No factor correlation data available</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const renderCorrelationHeatmap = () => {
    if (!data.correlation_matrix) return null;

    const factors = data.factor_list.slice(0, analysisOptions.max_factors);
    
    return (
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse bg-white">
          <thead>
            <tr>
              <th className="p-3 border border-gray-200 bg-gray-50"></th>
              {factors.map(factor => (
                <th key={factor} className="p-2 border border-gray-200 bg-gray-50 text-xs font-medium text-gray-700">
                  <div className="transform -rotate-45 whitespace-nowrap" style={{ height: '60px', display: 'flex', alignItems: 'end' }}>
                    {factor}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {factors.map(rowFactor => (
              <tr key={rowFactor}>
                <td className="p-3 border border-gray-200 bg-gray-50 font-medium text-xs text-gray-700 max-w-32 truncate">
                  {rowFactor}
                </td>
                {factors.map(colFactor => {
                  const correlation = data.correlation_matrix[rowFactor]?.[colFactor] || 0;
                  const intensity = Math.abs(correlation);
                  const isNegative = correlation < 0;
                  const isClickable = Math.abs(correlation) > 0.3;
                  
                  return (
                    <td 
                      key={colFactor}
                      className={`p-2 border border-gray-200 text-center text-xs font-medium ${
                        isClickable ? 'cursor-pointer hover:opacity-80' : 'cursor-default'
                      }`}
                      style={{
                        backgroundColor: rowFactor === colFactor ? '#f3f4f6' : 
                          isNegative 
                            ? `rgba(239, 68, 68, ${intensity * 0.7})` 
                            : `rgba(34, 197, 94, ${intensity * 0.7})`,
                        color: intensity > 0.5 ? 'white' : '#374151'
                      }}
                      onClick={() => {
                        if (isClickable && rowFactor !== colFactor) {
                          onRecommendationRequest(rowFactor);
                        }
                      }}
                      title={`${rowFactor} vs ${colFactor}: ${correlation.toFixed(3)}`}
                    >
                      {rowFactor === colFactor ? '1.00' : correlation.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const getQualityColor = (score: string) => {
    switch (score) {
      case 'excellent': return 'text-green-700 bg-green-50 border-green-200';
      case 'good': return 'text-blue-700 bg-blue-50 border-blue-200';
      case 'fair': return 'text-yellow-700 bg-yellow-50 border-yellow-200';
      case 'poor': return 'text-red-700 bg-red-50 border-red-200';
      default: return 'text-gray-700 bg-gray-50 border-gray-200';
    }
  };

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Header Card with Controls */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center space-x-2">
              <TrendingUp className="h-5 w-5 text-blue-600" />
              <span>Factor Correlation Matrix</span>
            </CardTitle>
            <div className="flex items-center space-x-3">
              <select 
                value={analysisOptions.max_factors} 
                onChange={(e) => onOptionsUpdate({ max_factors: Number(e.target.value) })}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={10}>Top 10 Factors</option>
                <option value={15}>Top 15 Factors</option>
                <option value={25}>Top 25 Factors</option>
              </select>
              <Button 
                onClick={onRefresh} 
                disabled={loading} 
                variant="outline"
                size="sm"
                className="flex items-center space-x-2"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                <span>Refresh</span>
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Data Quality Summary */}
      <Card>
        <CardContent className="p-6">
          <div className={`rounded-lg border p-4 ${getQualityColor(data.data_quality.quality_score)}`}>
            <div className="flex items-center mb-3">
              <Info className="h-4 w-4 mr-2" />
              <span className="font-medium">Analysis Quality: {data.data_quality.quality_score.toUpperCase()}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="font-medium">Factors Analyzed:</span>
                <span className="ml-2">{data.data_quality.factors_analyzed}</span>
              </div>
              <div>
                <span className="font-medium">Data Coverage:</span>
                <span className="ml-2">{data.data_quality.data_coverage_percent.toFixed(1)}%</span>
              </div>
              <div>
                <span className="font-medium">Excluded Factors:</span>
                <span className="ml-2">{data.data_quality.factors_excluded}</span>
              </div>
              <div>
                <span className="font-medium">Quality Score:</span>
                <span className="ml-2 capitalize">{data.data_quality.quality_score}</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Correlation Matrix */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Correlation Heatmap</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {renderCorrelationHeatmap()}
            
            {/* Legend */}
            <div className="flex items-center justify-center space-x-6 text-sm text-gray-600 pt-4 border-t">
              <div className="flex items-center space-x-2">
                <div className="w-4 h-4 bg-red-400 rounded"></div>
                <span>Negative Correlation</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-4 h-4 bg-green-400 rounded"></div>
                <span>Positive Correlation</span>
              </div>
              <div className="flex items-center space-x-2">
                <TrendingDown className="h-4 w-4 text-blue-600" />
                <span>Click cells with |correlation| > 0.3 for offset recommendations</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Strongest Correlations Summary */}
      {data.strongest_correlations && data.strongest_correlations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Strongest Factor Relationships</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {data.strongest_correlations.slice(0, 5).map((corr, index) => (
                <div key={index} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <div className="flex items-center space-x-3">
                    <span className="font-medium text-sm">{corr.factor1}</span>
                    <span className="text-gray-500">↔</span>
                    <span className="font-medium text-sm">{corr.factor2}</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                      corr.strength === 'strong' ? 'bg-red-100 text-red-700' :
                      corr.strength === 'moderate' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-blue-100 text-blue-700'
                    }`}>
                      {corr.strength}
                    </span>
                    <span className="font-mono text-sm">{corr.correlation.toFixed(3)}</span>
                    <Button
                      onClick={() => onRecommendationRequest(corr.factor1)}
                      size="sm"
                      variant="outline"
                      className="text-xs"
                    >
                      Get Recommendations
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default FactorIntelligenceView;
```

### **6. 🔄 Integration with Existing Systems**

```python
# /app.py - Add router registration following existing pattern

# === Register Routers ===
"""
FastAPI Router Registration - Updated with Factor Intelligence Engine

This section imports and registers all modular route handlers using FastAPI's APIRouter pattern.
Each router handles a specific domain of functionality with consistent middleware and documentation.

Updated Router Architecture:
===========================
🔐 **auth_router** (/auth/*): User authentication, session management, Google OAuth
📝 **frontend_logging_router** (/api/frontend/*): Client-side error tracking and analytics
🏦 **plaid_router** (/plaid/*): Financial account integration and portfolio data import
🤖 **claude_router** (/claude/*): AI-powered portfolio analysis and natural language insights
⚙️ **admin_router** (/admin/*): System administration, monitoring, and maintenance
🧮 **factor_intelligence_router** (/api/factor-intelligence/*): Factor analysis and market intelligence [NEW]
📊 **factor_groups_router** (/api/factor-groups/*): User-defined factor group management [NEW]
"""

# Import existing routers
from routes.auth import auth_router
from routes.frontend_logging import frontend_logging_router  
from routes.plaid import plaid_router
from routes.claude import claude_router
from routes.snaptrade import snaptrade_router
from routes.provider_routing_api import router as provider_routing_router

# Import new Factor Intelligence routers
from routes.factor_intelligence import factor_intelligence_router, factor_groups_router

# Register all routers with the main FastAPI application
app.include_router(auth_router)                    # Authentication & session management
app.include_router(frontend_logging_router)        # Frontend error tracking
app.include_router(plaid_router)                   # Financial data integration
app.include_router(snaptrade_router)               # SnapTrade brokerage integration
app.include_router(provider_routing_router)        # Provider routing & institution support
app.include_router(claude_router)                  # AI portfolio analysis
app.include_router(factor_intelligence_router)     # Factor Intelligence Engine [NEW]
app.include_router(factor_groups_router)           # Factor Group Management [NEW]


### **7. 📋 Implementation Order & Milestones**

```markdown
## Implementation Roadmap

### Phase 1: Foundation (Week 1-2) ✅ COMPLETE
- [x] **Database Migration**: Create `user_factor_groups` table
- [x] **Core Implementation**: Build factor intelligence core functions
- [x] **Service Layer**: Implement `FactorIntelligenceService` with caching
- [x] **Unit Tests**: Test core functionality and data validation

### Phase 2: API Layer (Week 3) ✅ COMPLETE
- [x] **Pydantic Models**: Create request/response models
- [x] **API Routes**: Implement `/routes/factor_intelligence.py`
- [x] **Integration**: Update `ServiceManager` and router registration
- [x] **API Tests**: Test all endpoints with various scenarios

### Phase 2b: MCP Tools (post-plan) ✅ COMPLETE
- [x] **get_factor_analysis**: Correlations, performance, and returns analysis modes
- [x] **get_factor_recommendations**: Single-factor and portfolio-mode offset recommendations
- [x] **Section filtering**: `include` param with `FACTOR_ANALYSIS_SECTIONS` (15 sections)
- [x] **Returns mode**: Lightweight trailing-window factor returns (multiple windows in one call)
- [x] **Fuzzy factor matching**: Normalized + alias + substring matching for factor names (Bug 5 fix)
- [x] **analyze_stock**: Standalone ticker analysis with factor proxy fallback (Bug 1 fix)

### Phase 3: Frontend Integration (Week 4) ❌ NOT STARTED
- [ ] **API Client**: TypeScript interfaces and API client methods
- [ ] **Core Components**: Factor correlation matrix and performance profiles
- [ ] **Factor Group Builder**: UI for creating and managing factor groups
- [ ] **Integration**: Connect with existing portfolio analysis UI

### Phase 4: Advanced Features (Week 5-6) ❌ NOT STARTED
- [ ] **Offset Recommendations**: Portfolio-aware recommendation UI
- [ ] **Data Visualization**: Interactive correlation heatmaps and charts
- [ ] **User Experience**: Form validation, loading states, error handling
- [ ] **Performance Optimization**: Caching strategies and lazy loading

### Phase 5: Testing & Deployment (Week 7) 🔄 PARTIAL
- [ ] **End-to-End Tests**: Complete user workflows
- [ ] **Performance Testing**: Load testing and optimization
- [x] **Documentation**: API schemas created (`docs/schemas/api/`)
- [x] **Production Deployment**: Database migration and feature rollout (backend)

### Success Metrics
- [x] Factor correlation analysis completes in <10 seconds
- [x] Cache hit rate >80% for repeated analysis (ServiceCacheMixin configured)
- [x] User can create factor groups with market-cap weighting
- [x] Offset recommendations consider current portfolio exposures
- [x] All endpoints follow existing authentication and error patterns
```

## **Architecture Benefits**

### **✅ Seamless Integration**
- **Consistent Patterns**: Follows existing FastAPI, Pydantic, and service layer patterns
- **Authentication**: Uses established `get_current_user()` dependency injection
- **Error Handling**: Standardized HTTPException responses with error codes
- **Logging**: Comprehensive logging with existing decorators

### **🚀 Performance Optimized**
- **Caching Strategy**: 30-minute TTL with thread-safe operations
- **Database Efficiency**: Proper indexing and user isolation
- **Async Support**: Ready for async wrapper implementation
- **Rate Limiting**: Tier-based limits following existing patterns

### **🔒 Security & Compliance**
- **User Isolation**: Complete data separation with user_id foreign keys
- **Input Validation**: Comprehensive Pydantic model validation
- **SQL Injection Protection**: Parameterized queries and ORM usage
- **Audit Trails**: Full logging of all operations

### **📈 Scalability**
- **Modular Architecture**: Clean separation of concerns
- **Database Design**: Optimized for growth with proper indexing
- **Caching Strategy**: Reduces computational load for repeated operations
- **API Design**: RESTful endpoints that scale horizontally

## **Configuration Management & Monitoring**

### **Environment Variables**

Add these configuration variables to your `.env` file:

```bash
# Factor Intelligence Engine Configuration
FACTOR_INTELLIGENCE_CACHE_TTL=1800           # Cache TTL (30 minutes)
FACTOR_INTELLIGENCE_MAX_FACTORS=200          # Max factors in correlation matrix
FACTOR_CORRELATION_MIN_OBSERVATIONS=24       # Min data requirement (months)
FACTOR_CORRELATION_TIMEOUT=30                # Analysis timeout (seconds)
YFINANCE_TIMEOUT=10                          # Market cap data timeout
YFINANCE_MAX_RETRIES=3                       # Market cap retry attempts

# Rate Limiting (public/registered/paid tiers)
FACTOR_CORRELATIONS_RATE_LIMIT="50 per day;100 per day;200 per day"
FACTOR_PERFORMANCE_RATE_LIMIT="50 per day;100 per day;200 per day"
FACTOR_RECOMMENDATIONS_RATE_LIMIT="30 per day;60 per day;120 per day"
FACTOR_GROUPS_CREATE_RATE_LIMIT="20 per day;40 per day;80 per day"
FACTOR_GROUPS_LIST_RATE_LIMIT="100 per day;200 per day;500 per day"

# Data Quality Thresholds
FACTOR_GROUP_MIN_TICKERS=2
FACTOR_GROUP_MAX_TICKERS=50
FACTOR_CORRELATION_THRESHOLD_DEFAULT=-0.2
```

### **Health Check Endpoints**

Add monitoring endpoints to `/routes/factor_intelligence.py`:

```python
@factor_intelligence_router.get("/health")
@log_api_health("FactorIntelligence", "health")
async def factor_intelligence_health(
    request: Request,
    user: dict = Depends(get_current_user),
    service: FactorIntelligenceService = Depends(lambda user=Depends(get_current_user): get_user_factor_intelligence_service(user))
):
    """Health check with cache statistics and configuration info"""
    try:
        cache_stats = service.get_cache_stats()
        return {
            "status": "healthy",
            "cache_stats": cache_stats,
            "configuration": {
                "max_factors": FACTOR_INTELLIGENCE_MAX_FACTORS,
                "min_observations": FACTOR_CORRELATION_MIN_OBSERVATIONS,
                "correlation_timeout": FACTOR_CORRELATION_TIMEOUT
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@factor_groups_router.get("/health")
@log_api_health("FactorGroups", "health")
async def factor_groups_health(
    request: Request,
    user: dict = Depends(get_current_user)
):
    """Health check for factor groups with database connectivity test"""
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            user_groups_count = len(db_client.get_user_factor_groups(user['user_id']))
        
        return {
            "status": "healthy",
            "database_connected": True,
            "user_groups_count": user_groups_count
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### **Enhanced Service Monitoring**

Update `FactorIntelligenceService` with monitoring counters:

```python
class FactorIntelligenceService(ServiceCacheMixin):
    def __init__(self, cache_results: bool = True):
        self.cache_results = cache_results
        self._init_service_cache()
        
        # Enhanced monitoring counters
        self._cache_hits = 0
        self._cache_requests = 0
        self._analysis_count = 0
        self._error_count = 0
        self._total_execution_time = 0.0
        self._memory_usage_peak = 0.0
        
    @log_cache_operations
    @log_performance(10.0)  # 10 second threshold
    @log_resource_usage_decorator
    def analyze_factor_correlations(self, analysis_data: FactorAnalysisData) -> FactorCorrelationResult:
        """Factor correlation analysis with comprehensive performance monitoring."""
        
        import time
        import psutil
        
        self._cache_requests += 1
        cache_key = analysis_data.get_cache_key()
        
        # Check cache first
        if self.cache_results and cache_key in self.cache:
            self._cache_hits += 1
            log_performance_metric("factor_correlation_cache_hit", 0.001, {
                'cache_key': cache_key[:50],  # Truncated for logging
                'cache_hit_rate': self._cache_hits / self._cache_requests
            })
            return self.cache[cache_key]
        
        # Cache miss - perform analysis with performance tracking
        start_time = time.time()
        initial_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        
        try:
            # Call core function (would be imported from core/factor_intelligence.py)
            result = analyze_factor_correlations(analysis_data)
            
            # Cache the result
            if self.cache_results:
                self.cache[cache_key] = result
            
            # Update performance metrics
            execution_time = time.time() - start_time
            final_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            memory_delta = final_memory - initial_memory
            
            self._analysis_count += 1
            self._total_execution_time += execution_time
            self._memory_usage_peak = max(self._memory_usage_peak, memory_delta)
            
            log_performance_metric("factor_correlation_analysis", execution_time, {
                'factors_analyzed': len(analysis_data.factors) if hasattr(analysis_data, 'factors') else 0,
                'cache_hit_rate': self._cache_hits / self._cache_requests,
                'average_execution_time': self._total_execution_time / self._analysis_count,
                'memory_usage_mb': memory_delta,
                'peak_memory_mb': self._memory_usage_peak,
                'total_analyses': self._analysis_count
            })
            
            return result
            
        except Exception as e:
            self._error_count += 1
            execution_time = time.time() - start_time
            
            log_performance_metric("factor_correlation_error", execution_time, {
                'error_type': type(e).__name__,
                'error_rate': self._error_count / (self._analysis_count + self._error_count),
                'memory_usage_mb': psutil.Process().memory_info().rss / 1024 / 1024 - initial_memory
            })
            raise
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        return {
            'cache_hit_rate': self._cache_hits / max(self._cache_requests, 1),
            'total_cache_requests': self._cache_requests,
            'total_cache_hits': self._cache_hits,
            'total_analyses': self._analysis_count,
            'total_errors': self._error_count,
            'error_rate': self._error_count / max(self._analysis_count + self._error_count, 1),
            'average_execution_time': self._total_execution_time / max(self._analysis_count, 1),
            'peak_memory_usage_mb': self._memory_usage_peak,
            'cache_size': len(self.cache),
            'cache_maxsize': self.cache.maxsize,
            'cache_ttl': self.cache.ttl
        }
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Enhanced statistics with hit rates and error tracking"""
        with self._lock:
            return {
                "cache_size": len(self._cache),
                "cache_maxsize": self._cache.maxsize,
                "cache_ttl": self._cache.ttl,
                "cache_hits": self._cache_hits,
                "cache_requests": self._cache_requests,
                "cache_hit_rate": self._cache_hits / max(self._cache_requests, 1),
                "analysis_count": self._analysis_count,
                "error_count": self._error_count,
                "error_rate": self._error_count / max(self._analysis_count, 1)
            }
```

## 🧪 Comprehensive Testing Strategy

Following your established **73-file test suite** architecture with AI-powered test orchestration:

### **Unit Tests** (`tests/factor_intelligence/unit/`)
```python
# tests/factor_intelligence/unit/test_factor_correlations.py
def test_analyze_factor_correlations_basic():
    """Test basic factor correlation analysis."""
    
def test_analyze_factor_correlations_insufficient_data():
    """Test handling of insufficient data scenarios."""
    
def test_factor_correlation_result_formatting():
    """Test formatted table output for AI context."""

# tests/factor_intelligence/unit/test_factor_performance.py  
def test_analyze_factor_performance_metrics():
    """Test factor performance calculation accuracy."""
    
def test_factor_performance_data_quality_checks():
    """Test minimum observation requirements."""

# tests/factor_intelligence/unit/test_offset_recommendations.py
def test_generate_offset_recommendations_portfolio_aware():
    """Test portfolio-aware recommendation logic."""
    
def test_offset_recommendations_correlation_filtering():
    """Test correlation-based filtering logic."""

# tests/factor_intelligence/unit/test_factor_groups.py
def test_create_factor_group_equal_weighted():
    """Test equal-weighted factor group creation."""
    
def test_create_factor_group_market_cap_weighted():
    """Test market-cap weighted factor group creation."""
```

### **Integration Tests** (`tests/factor_intelligence/integration/`)
```python
# tests/factor_intelligence/integration/test_factor_intelligence_api.py
def test_factor_correlations_endpoint_authenticated():
    """Test /api/factor-intelligence/correlations with authentication."""
    
def test_factor_performance_endpoint_rate_limiting():
    """Test rate limiting on factor performance endpoint."""
    
def test_offset_recommendations_portfolio_integration():
    """Test offset recommendations with real portfolio data."""

# tests/factor_intelligence/integration/test_factor_groups_api.py
def test_create_factor_group_database_persistence():
    """Test factor group creation and database storage."""
    
def test_factor_group_user_isolation():
    """Test user isolation for factor groups."""
```

### **E2E Tests** (`tests/e2e/factor-intelligence/`)
```javascript
// tests/e2e/factor-intelligence/factor-intelligence-workflow.spec.js
test('Complete factor intelligence workflow', async ({ page }) => {
  // 1. Login and navigate to factor intelligence
  // 2. Analyze factor correlations
  // 3. Generate offset recommendations
  // 4. Create custom factor group
  // 5. Verify results and UI updates
});

test('Factor intelligence error handling', async ({ page }) => {
  // Test insufficient data scenarios and error states
});
```

### **Performance Tests** (`tests/performance/factor_intelligence_benchmarks.py`)
```python
def test_factor_correlation_matrix_performance():
    """Benchmark large factor correlation matrix calculation."""
    # Target: < 10 seconds for 50+ factors
    
def test_factor_intelligence_memory_usage():
    """Monitor memory usage during factor analysis."""
    # Target: < 500MB peak memory usage
    
def test_factor_intelligence_cache_hit_rates():
    """Monitor cache effectiveness."""
    # Target: > 80% cache hit rate for repeated analyses
```

### **Testing Coverage Targets:**
- **Unit Tests**: 95%+ code coverage for core functions
- **Integration Tests**: 100% API endpoint coverage
- **E2E Tests**: 100% critical user workflow coverage
- **Performance Tests**: All operations under defined SLA thresholds
- **Security Tests**: Comprehensive penetration testing and audit compliance


This implementation architecture provides a complete blueprint for integrating the Factor Intelligence Engine into your existing system while maintaining all established patterns and ensuring production-ready quality with comprehensive testing, monitoring, and configuration management.
    Defaults:
    =========
    - market_sensitivity: Applies to ['industry','style'] by default; excludes 'market' category and any ETF used
      as a benchmark (e.g., SPY). Benchmarks default to ['SPY'] with optional ACWX/EEM.
    - rate_sensitivity: Applies to ['fixed_income','industry','market','cash'] by default. Maturities default to
      RATE_FACTOR_CONFIG (e.g., ['UST2Y','UST5Y','UST10Y','UST30Y']).
    - Windows: Correlations use centralized default windows from settings (e.g., PORTFOLIO_DEFAULTS or a dedicated
      INTELLIGENCE_WINDOWS). All sections use the same start/end unless overridden, ensuring consistency across views.
    - Rolling snapshots: Optional rolling summaries (e.g., 12/24/36 months) can be enabled to provide stability context.
    - Industry granularity:
      • Default 'group' uses `industry_proxies.sector_group` (DB‑first) when present; entries without a sector_group fall
        back to 'industry' for that entry. No ETF inference is used.
      • When 'group' is selected, the correlation matrix and sensitivity overlays for “industry” are computed from
        group composite return series (equal‑weight of member industries' ETF returns by default). No canonical group ETF
        is required.
### Performance & Scalability Notes

Goal: Keep ~25 ETFs (+ macro assets) responsive by caching and grouping strategies.

- Shared returns panel cache
  - Build a single aligned monthly returns panel for the requested universe/window and cache it by
    `f"factor_returns_panel_{universe_hash}_{start_date}_{end_date}_{total_return_flag}"`. Reuse for all sections (matrices, overlays, profiles).
  - TTL configurable; invalidate on universe change (e.g., proxies update) via a simple version token.

- Section‑level caches
  - Cache each computed section (per‑category matrices, macro composites/ETFs, overlays) with keys like
    `f"factor_{section_type}_{universe_hash}_{start_date}_{end_date}_{section_params_hash}"`.

- Curated macro ETF matrix
  - Opt‑in, disabled by default. Control size via:
    • `macro_max_per_group` (default 5)
    • `macro_deduplicate_threshold` (default 0.95) to drop near‑duplicates within a group
    • `macro_min_group_coverage_pct` to require minimum data coverage before including a group
  - If the matrix would exceed budget (N_groups * max_per_group^2 too large), fall back to macro composites
    and return a `data_quality` note.

- Tuning parameters (already exposed)
  - `macro_max_per_group`, `macro_deduplicate_threshold`, `macro_min_group_coverage_pct`, `top_n_per_matrix`.
  - Defaults chosen to balance fidelity and speed; callers can override.

- Fetching/batching
  - Batch price requests and reuse existing disk/cache layers from data_loader.
  - Respect provider rate limits; prefer cached total‑return series; fallback to close only when needed.

- Concurrency & budgets
  - Use constrained concurrency for computations; apply a time budget per heavy section.
  - Return partial results with clear `data_quality` messages when a budget is exceeded.

### Performance Monitoring

Instrument correlation and performance calculations with timing and size metrics to catch regressions,
especially when expanded beyond current ~25 ETF universe.

- Decorators
  - Keep using `@log_performance` and `@log_resource_usage_decorator` on service methods.

- Section timers (recorded per request and in service counters)
  - returns_panel_build_ms
  - per_category_corr_ms (per category), and total_corr_ms
  - macro_composite_ms, macro_etf_ms (if enabled)
  - rate_sensitivity_ms, market_sensitivity_ms
  - performance_profiles_ms, composite_performance_ms

- Size and coverage metrics
  - factors_count_total, factors_count_per_category
  - macro_groups_included, macro_constituents_used, macro_constituents_dropped
  - deduplicated_pairs_count (macro), coverage_pct_per_group

- Exposure in responses
  - Add `analysis_metadata.performance` with timing summaries and sizes (non-PII) so clients can surface performance data.
  - Keep service health counters (cache_hits/requests, analyses, errors, total_exec_time, peak_mem) in FactorIntelligenceService.

- Alerting (optional later)
  - Define soft thresholds for total_corr_ms and macro_etf_ms; emit warnings to logs when exceeded.

### Deployment Note: Moving End Date Defaults

- For production, set the default analysis end date to a moving latest month‑end so caches naturally refresh as data rolls.
- Centralize via settings (e.g., resolve end_date='latest_month_end' at runtime in AnalysisData). Start date may remain a
  fixed default (e.g., '2019-01-31') or a preset window (e.g., 3Y/5Y).

### Factor Lifecycle Management (Delistings / Ticker Changes)

Plan for ETF delistings, ticker changes, and stale proxies in the factor universe.

- Detection & Signals
  - During returns panel build, if a proxy has no data or chronically fails (e.g., no observations ≥ min threshold),
    record it under `data_quality.stale_factor_candidates` with reason (no_data, fetch_failed, thin_history).
  - Maintain a simple counter for consecutive failures per proxy (in memory or DB) to avoid transient flags.

- Data-quality thresholds (centralized)
  - Reuse `settings.DATA_QUALITY_THRESHOLDS` (e.g., `min_observations_for_returns_calculation`) to decide when to
    exclude a proxy and flag as stale.

- Universe loader behavior
  - Skip excluded (stale) proxies for calculations; include them in `excluded_factor_list` with reasons.
  - For macro/group composites, report coverage impact per group.

- Database (optional extensions)
  - `asset_etf_proxies`: consider adding `active BOOLEAN DEFAULT TRUE`, `last_verified_at TIMESTAMP`, `notes TEXT`.
  - `industry_proxies`: consider adding `last_verified_at TIMESTAMP`.
  - These are optional; v1 can rely on runtime `data_quality` signals and admin review.

- Admin workflows
  - Extend `manage_reference_data.py` with:
    • `asset-proxy replace <asset_class> <proxy_key> <old_etf> <new_etf>`
    • `asset-proxy deactivate <asset_class> <proxy_key> <etf>`
    • `industry add <industry> <etf> [--asset-class] [--group]` (already planned)
  - Add a `verify_proxies` utility (CLI) that attempts a lightweight price fetch for all active proxies and prints a
    summary report of stale candidates.

- Analysis metadata
  - Include `analysis_metadata.lifecycle` with: `stale_factor_candidates`, `excluded_for_no_data`, and optional
    `last_universe_refresh` timestamps to surface lifecycle health to clients.
