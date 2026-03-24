#!/usr/bin/env python
"""
SnapTrade Integration Loader

This module provides integration with SnapTrade API for portfolio management,
mirroring the patterns used in plaid_loader.py. Supports broker connections
like Fidelity, Schwab, and others not covered by Plaid.

KEY ARCHITECTURAL DECISIONS:

🔄 ENHANCED SECURITY TYPE CLASSIFICATION:
- Cash-Only Preservation: Preserves ONLY SnapTrade cash classifications (trusted for banking data)
- FMP-First Enhancement: Uses SecurityTypeService (FMP) for ALL non-cash securities
- Fallback Strategy: Uses original SnapTrade classification when FMP unavailable
- Comprehensive Coverage: Enhances all securities (equity, etf, mutual_fund, etc.) via FMP

💰 HYBRID CASH + SECURITIES FETCHING:
- Securities: get_user_account_positions (SnapTrade recommended, includes type info)
- Cash: get_user_account_balance (positions endpoint excludes cash)
- Combined: Unified holdings list with consistent type classification

🏦 CASH MAPPING INTEGRATION:
- SnapTrade cash → CUR:USD ticker → SGOV proxy (via portfolio_manager._apply_cash_mapping)
- Cash stored as {'dollars': value}, securities as {'shares': quantity}
- Supports negative quantities (shorts) unlike some other integrations

📊 DATA PIPELINE FLOW:
SnapTrade API (unified endpoint) → fetch_snaptrade_holdings → Selective SecurityTypeService enhancement → PortfolioData

🔗 UNIFIED ENDPOINT ARCHITECTURE:
- Holdings: get_user_account_positions → Securities AND cash in same response
- Cash Detection: Early cash check in get_enhanced_security_type() required
- Integration: Cash mixed with securities, needs filtering (unlike Plaid's separation)
- Result: Cash flows through enhancement logic but gets preserved immediately

CLASSIFICATION LOGIC:
- Cash positions: Preserve SnapTrade classification (trusted for banking data)
- All securities: Enhance with SecurityTypeService (FMP) - equity, etf, mutual_fund, etc.
- Fallback: Original SnapTrade classification when FMP unavailable or fails

Key Features:
- SDK-based integration (snaptrade-python-sdk)
- AWS Secrets Manager for credential storage  
- Multi-account consolidation with type preservation
- Intelligent SecurityTypeService integration (enhancement-only approach)
- Normalization to standard portfolio format
- Provider-specific position management
- Comprehensive error handling and retry logic
"""

import math
import os
import boto3
import json
import pandas as pd
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any, TYPE_CHECKING, Union
from botocore.exceptions import ClientError, BotoCoreError

# Logging (import first to use in SDK imports)
from utils.logging import log_error, log_portfolio_operation, portfolio_logger

# SnapTrade SDK imports
if TYPE_CHECKING:
    from snaptrade_client import SnapTrade, ApiException
else:
    try:
        from snaptrade_client import SnapTrade, ApiException
        portfolio_logger.info("✅ SnapTrade SDK imported successfully")
    except ImportError as e:
        portfolio_logger.warning(f"⚠️ SnapTrade SDK not available: {e}")
        portfolio_logger.warning("Run: pip install snaptrade-python-sdk")
        # Create dummy classes for runtime when SDK not available
        class SnapTrade:
            pass
        class ApiException(Exception):
            pass

# Environment configuration
from settings import PORTFOLIO_DEFAULTS, FRONTEND_BASE_URL

# Import SecurityTypeService for enhanced security classification
try:
    from services.security_type_service import SecurityTypeService
    portfolio_logger.debug("✅ SecurityTypeService successfully imported in snaptrade_loader")
except ImportError as e:
    SecurityTypeService = None
    portfolio_logger.error(f"❌ SecurityTypeService import failed in snaptrade_loader: {e}")
    portfolio_logger.warning("⚠️ Falling back to SnapTrade-only classification (no FMP enhancement)")


# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 SNAPTRADE SDK CLIENT SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def get_snaptrade_client(region_name: str = "us-east-1") -> Optional[SnapTrade]:
    """
    Initialize SnapTrade SDK client with credentials from AWS Secrets Manager.
    
    Args:
        region_name: AWS region for secrets retrieval
        
    Returns:
        SnapTrade: Initialized client or None if feature disabled/SDK unavailable
    """
    # SnapTrade is always enabled
        
    if not SnapTrade:
        portfolio_logger.warning("⚠️ SnapTrade SDK not available")
        return None
        
    try:
        app_credentials = get_snaptrade_app_credentials(region_name)
        
        client = SnapTrade(
            consumer_key=app_credentials['consumer_key'],
            client_id=app_credentials['client_id']
        )
        
        # Note: Environment configuration is handled automatically by the SDK
        # Production and sandbox use the same base URL with different credentials
                
        portfolio_logger.info("✅ SnapTrade client initialized successfully")
        return client
        
    except Exception as e:
        log_error("snaptrade_client", "initialization", e)
        portfolio_logger.error(f"❌ Failed to initialize SnapTrade client: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 🔐 AWS SECRETS MANAGER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def store_snaptrade_app_credentials(client_id: str, consumer_key: str, 
                                  environment: str, region_name: str = "us-east-1"):
    """
    Store SnapTrade app-level credentials in AWS Secrets Manager.
    
    Args:
        client_id: SnapTrade application client ID
        consumer_key: SnapTrade application consumer key
        environment: 'sandbox' or 'production'
        region_name: AWS region for storage
    """
    secret_name = f"snaptrade/app_credentials/{environment}"
    
    secret_value = {
        "client_id": client_id,
        "consumer_key": consumer_key,
        "environment": environment
    }
    
    try:
        secrets_client = boto3.client('secretsmanager', region_name=region_name)
        
        # Try to create the secret first
        try:
            secrets_client.create_secret(
                Name=secret_name,
                SecretString=json.dumps(secret_value),
                Description=f"SnapTrade app credentials for {environment}"
            )
            portfolio_logger.info(f"✅ Created new SnapTrade app credentials for {environment}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceExistsException':
                # Secret exists, update it
                secrets_client.put_secret_value(
                    SecretId=secret_name,
                    SecretString=json.dumps(secret_value)
                )
                portfolio_logger.info(f"✅ Updated SnapTrade app credentials for {environment}")
            else:
                raise
        
    except Exception as e:
        log_error("snaptrade_secrets", "store_app_credentials", e)
        raise


def get_snaptrade_app_credentials(region_name: str = "us-east-1") -> Dict[str, str]:
    """
    Retrieve SnapTrade app-level credentials from AWS Secrets Manager or environment.
    
    Priority:
    1. Environment variables (for development)
    2. AWS Secrets Manager (for production)
    
    Args:
        region_name: AWS region for retrieval
        
    Returns:
        Dict containing client_id, consumer_key, and environment
    """
    environment = os.getenv("SNAPTRADE_ENVIRONMENT", "production")
    
    # Try environment variables first (simpler for development)
    client_id = os.getenv("SNAPTRADE_CLIENT_ID")
    consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY")
    
    if client_id and consumer_key:
        portfolio_logger.info("✅ Using SnapTrade credentials from environment variables")
        return {
            "client_id": client_id,
            "consumer_key": consumer_key,
            "environment": environment
        }
    
    # Fallback to AWS Secrets Manager
    portfolio_logger.info("🔍 Environment variables not found, trying AWS Secrets Manager...")
    secret_name = f"snaptrade/app_credentials/{environment}"
    
    try:
        secrets_client = boto3.client('secretsmanager', region_name=region_name)
        response = secrets_client.get_secret_value(SecretId=secret_name)
        credentials = json.loads(response['SecretString'])
        portfolio_logger.info("✅ Using SnapTrade credentials from AWS Secrets Manager")
        return credentials
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            portfolio_logger.error(f"❌ AWS Secret '{secret_name}' not found")
        else:
            portfolio_logger.error(f"❌ AWS Secrets Manager error: {e}")
            
        log_error("snaptrade_secrets", "get_app_credentials", e)
        raise Exception(f"SnapTrade credentials not found in environment variables or AWS Secrets Manager")


def store_snaptrade_user_secret(user_email: str, user_secret: str, region_name: str = "us-east-1"):
    """
    Store SnapTrade user secret in AWS Secrets Manager.
    
    Args:
        user_email: User email address (consistent with Plaid pattern)
        user_secret: SnapTrade-generated user secret
        region_name: AWS region for storage
    """
    # Use email directly for secret name (consistent with Plaid)
    secret_name = f"snaptrade/user_secret/{user_email}"
    
    secret_value = {
        "user_email": user_email,
        "user_secret": user_secret,
        "created_at": datetime.now().isoformat()
    }
    
    try:
        secrets_client = boto3.client('secretsmanager', region_name=region_name)
        
        # Try to create the secret first
        try:
            secrets_client.create_secret(
                Name=secret_name,
                SecretString=json.dumps(secret_value),
                Description=f"SnapTrade user secret for {user_email}"
            )
            portfolio_logger.info(f"✅ Created new SnapTrade user secret for user {user_email} in AWS Secrets Manager")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceExistsException':
                # Secret exists, update it
                secrets_client.put_secret_value(
                    SecretId=secret_name,
                    SecretString=json.dumps(secret_value)
                )
                portfolio_logger.info(f"✅ Updated SnapTrade user secret for user {user_email} in AWS Secrets Manager")
            else:
                raise
        
    except Exception as e:
        portfolio_logger.warning(f"⚠️ Could not store user secret in AWS Secrets Manager: {e}")
        portfolio_logger.warning(f"💡 For production, ensure AWS credentials are configured")
        log_error("snaptrade_secrets", "store_user_secret", e)
        raise


def get_snaptrade_user_secret(user_email: str, region_name: str = "us-east-1") -> Optional[str]:
    """
    Retrieve SnapTrade user secret from AWS Secrets Manager.
    Returns None only when the secret is not found.
    
    Args:
        user_email: User email address (consistent with Plaid pattern)
        region_name: AWS region for retrieval
        
    Returns:
        User secret string or None if not found
    """
    # Use email directly for secret name (consistent with Plaid)
    secret_name = f"snaptrade/user_secret/{user_email}"
    
    try:
        secrets_client = boto3.client('secretsmanager', region_name=region_name)
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response['SecretString'])
        return secret_data.get('user_secret')
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return None
        portfolio_logger.warning(f"⚠️ AWS Secrets Manager error when retrieving user secret: {e}")
        log_error("snaptrade_secrets", "get_user_secret", e)
        raise RuntimeError(f"Failed to retrieve SnapTrade user secret from AWS Secrets Manager: {e}") from e
    except BotoCoreError as e:
        portfolio_logger.warning(f"⚠️ Could not retrieve user secret from AWS: {e}")
        log_error("snaptrade_secrets", "get_user_secret", e)
        raise RuntimeError(f"Failed to retrieve SnapTrade user secret from AWS Secrets Manager: {e}") from e


def delete_snaptrade_user_secret(user_email: str, region_name: str = "us-east-1"):
    """
    Delete SnapTrade user secret from AWS Secrets Manager.
    
    Args:
        user_email: User email address
        region_name: AWS region for deletion
    """
    # Use email directly for secret name (consistent with Plaid)
    secret_name = f"snaptrade/user_secret/{user_email}"
    
    try:
        secrets_client = boto3.client('secretsmanager', region_name=region_name)
        secrets_client.delete_secret(SecretId=secret_name, RecoveryWindowInDays=7)
        portfolio_logger.info(f"✅ Deleted SnapTrade user secret for user {user_email}")
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            portfolio_logger.info(f"ℹ️ SnapTrade user secret not found for user {user_email}")
            return
        log_error("snaptrade_secrets", "delete_user_secret", e)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_snaptrade_user_id_from_email(email: str) -> str:
    """
    Generate consistent, immutable user ID for SnapTrade API from email.
    
    Args:
        email: User email address
        
    Returns:
        str: Stable user ID for SnapTrade (format: "user_{hash}")
    """
    user_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    return f"user_{user_hash}"

# ═══════════════════════════════════════════════════════════════════════════════
# 👤 USER MANAGEMENT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def register_snaptrade_user(user_email: str, client: SnapTrade) -> str:
    """
    Register a new user with SnapTrade and store their user secret.
    
    Args:
        user_email: User email address
        client: Initialized SnapTrade client
        
    Returns:
        User secret for future API calls
    """
    try:
        # Generate SnapTrade user ID from email (privacy-friendly)
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]
        
        # Register user with SnapTrade API (with retry logic)
        response = _register_snap_trade_user_with_retry(client, snaptrade_user_id)
        
        user_secret = response.body["userSecret"]
        
        # Store user secret using email (backend only, never sent to SnapTrade)
        store_snaptrade_user_secret(user_email, user_secret)
        
        portfolio_logger.info(f"✅ Registered SnapTrade user: {user_hash}")
        return user_secret
        
    except ApiException as e:
        if "already exist" in str(e).lower():
            # User already exists in SnapTrade
            portfolio_logger.info(f"ℹ️ SnapTrade user already exists: {user_hash}")
            
            # Check if we have their secret stored in AWS
            existing_secret = get_snaptrade_user_secret(user_email)
            if existing_secret and not existing_secret.startswith("needs_reconnection_"):
                portfolio_logger.info(f"✅ Using stored secret for existing user: {user_hash}")
                return existing_secret
            if existing_secret and existing_secret.startswith("needs_reconnection_"):
                portfolio_logger.warning(f"⚠️ Found reconnection marker for existing SnapTrade user: {user_hash}")
            else:
                portfolio_logger.warning(f"⚠️ User exists in SnapTrade but no secret in AWS storage")
            raise RuntimeError(
                "SnapTrade user exists but no valid AWS user secret is available. "
                "Automatic delete/recreate is disabled to protect brokerage connections. "
                "Operator action required: manually re-register this user to restore credentials."
            )
                
        log_error("snaptrade_user", "register_user", e)
        raise
    except Exception as e:
        log_error("snaptrade_user", "register_user", e)
        raise


def delete_snaptrade_user(user_email: str, client: SnapTrade):
    """
    Delete SnapTrade user and clean up local storage.
    
    Args:
        user_email: User email address
        client: Initialized SnapTrade client
    """
    try:
        # Generate SnapTrade user ID from email (privacy-friendly)
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]

        # Delete user from SnapTrade (doesn't require user secret)
        _delete_snap_trade_user_with_retry(client, snaptrade_user_id)

        # Clean up AWS secret if it exists
        delete_snaptrade_user_secret(user_email)

        portfolio_logger.info(f"✅ Deleted SnapTrade user: {user_hash}")
        
    except ApiException as e:
        if "not found" in str(e).lower():
            # User doesn't exist on SnapTrade, just clean up locally
            delete_snaptrade_user_secret(user_email)
            portfolio_logger.info(f"ℹ️ SnapTrade user not found, cleaned up locally: {user_hash}")
            return
            
        log_error("snaptrade_user", "delete_user", e)
        raise
    except Exception as e:
        log_error("snaptrade_user", "delete_user", e)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# 🔗 CONNECTION MANAGEMENT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def create_snaptrade_connection_url(
    user_email: str,
    client: SnapTrade,
    connection_type: str = "trade",
) -> str:
    """
    Create SnapTrade connection URL for account linking.

    Args:
        user_email: User email address
        client: Initialized SnapTrade client
        connection_type: Connection permission level — "trade" (default) or "read".
            Use "trade" to enable order placement through the connection.

    Returns:
        Connection URL for frontend redirection
    """
    try:
        # Generate SnapTrade user ID from email (privacy-friendly)
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]
        user_secret = get_snaptrade_user_secret(user_email)

        if not user_secret:
            # Register user if they don't exist
            user_secret = register_snaptrade_user(user_email, client)

        # Create connection URL (with retry logic)
        response = _login_snap_trade_user_with_retry(
            client, snaptrade_user_id, user_secret,
            broker=None,  # Let user choose broker
            immediate_redirect=True,
            custom_redirect=f"{FRONTEND_BASE_URL}/snaptrade/success",
            connection_type=connection_type,
        )

        return response.body["redirectURI"]

    except Exception as e:
        log_error("snaptrade_connection", "create_url", e)
        raise


def upgrade_snaptrade_connection_to_trade(
    user_email: str,
    authorization_id: str,
    client: Optional[SnapTrade] = None,
) -> str:
    """
    Upgrade an existing read-only SnapTrade connection to trading-enabled.

    Per SnapTrade docs, this re-authorizes the connection by passing
    ``reconnect=<authorization_id>`` with ``connection_type="trade"``.
    The returned URL must be opened in a browser for the user to
    re-authenticate with their brokerage.

    Args:
        user_email: User email address
        authorization_id: Existing SnapTrade brokerage authorization ID
        client: Optional pre-initialized SnapTrade client

    Returns:
        Redirect URL for re-authorization with trading permissions
    """
    if not client:
        client = get_snaptrade_client()
    if not client:
        raise ValueError("SnapTrade client unavailable")

    try:
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_secret = get_snaptrade_user_secret(user_email)

        if not user_secret:
            raise ValueError(f"No SnapTrade user secret found for {user_email}")

        response = _login_snap_trade_user_with_retry(
            client, snaptrade_user_id, user_secret,
            immediate_redirect=False,
            connection_type="trade",
            reconnect=authorization_id,
        )

        redirect_uri = response.body["redirectURI"]
        portfolio_logger.info(
            f"✅ Generated trading upgrade URL for authorization {authorization_id}"
        )
        return redirect_uri

    except Exception as e:
        log_error("snaptrade_connection", "upgrade_to_trade", e)
        raise


def list_snaptrade_connections(user_email: str, client: SnapTrade) -> List[Dict]:
    """
    List user's SnapTrade brokerage connections.
    
    Args:
        user_email: User email address
        client: Initialized SnapTrade client
        
    Returns:
        List of connection dictionaries with account info
    """
    try:
        # Generate SnapTrade user ID from email (privacy-friendly)
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]
        user_secret = get_snaptrade_user_secret(user_email)
        
        if not user_secret:
            return []
            
        # Get all accounts (which represent connections) (with retry logic)
        accounts_response = _list_user_accounts_with_retry(client, snaptrade_user_id, user_secret)
        
        # Extract accounts from API response
        accounts = accounts_response.body if hasattr(accounts_response, 'body') else accounts_response
        
        connections = []
        for account in accounts:
            connections.append({
                "authorization_id": account.get('brokerage_authorization'),
                "brokerage_name": account.get('institution_name', 'Unknown'),
                "account_id": account.get('id'),
                "account_name": account.get('name'),
                "account_number": account.get('number'),
                "account_type": account.get('meta', {}).get('type', 'Unknown'),
                "status": "active"
            })
            
        return connections
        
    except Exception as e:
        log_error("snaptrade_connection", "list_connections", e)
        raise


def check_snaptrade_connection_health(
    user_email: str,
    client: SnapTrade,
    probe_trading: bool = False,
) -> List[Dict]:
    """
    Check SnapTrade connection health grouped by brokerage authorization.

    Args:
        user_email: User email address
        client: Initialized SnapTrade client
        probe_trading: If True, probe symbol search with "AAPL" for each authorization

    Returns:
        List of per-authorization health records
    """

    def _normalize_authorization_id(auth_value: Any) -> Optional[str]:
        if isinstance(auth_value, dict):
            auth_id = auth_value.get("id")
            return str(auth_id) if auth_id else None
        if auth_value:
            return str(auth_value)
        return None

    try:
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]
        user_secret = get_snaptrade_user_secret(user_email)

        if not user_secret:
            return []

        portfolio_logger.debug(
            f"Running SnapTrade connection health check for user_hash={user_hash}, probe_trading={probe_trading}"
        )

        try:
            accounts_response = _list_user_accounts_with_retry(client, snaptrade_user_id, user_secret)
            accounts = accounts_response.body if hasattr(accounts_response, "body") else accounts_response
            if not isinstance(accounts, list):
                accounts = []
        except Exception as list_error:
            log_error("snaptrade_connection", "health_check_list_user_accounts", list_error)
            return []

        grouped: Dict[str, Dict[str, Any]] = {}
        for account in accounts:
            if not isinstance(account, dict):
                continue

            account_id = account.get("id")
            auth_id = _normalize_authorization_id(account.get("brokerage_authorization"))
            if not auth_id:
                auth_id = f"unknown:{account_id}" if account_id else "unknown"

            entry = grouped.setdefault(
                auth_id,
                {
                    "authorization_id": auth_id,
                    "brokerage_name": account.get("institution_name", "Unknown"),
                    "account_ids": [],
                    "probe_account_id": None,
                },
            )

            if account_id is not None:
                entry["account_ids"].append(str(account_id))
                if entry["probe_account_id"] is None:
                    entry["probe_account_id"] = str(account_id)

            if not entry.get("brokerage_name") and account.get("institution_name"):
                entry["brokerage_name"] = account.get("institution_name")

        health_results: List[Dict] = []
        for authorization_id, entry in grouped.items():
            brokerage_name = entry.get("brokerage_name") or "Unknown"
            connection_type = "unknown"
            disabled = False
            disabled_date = None

            try:
                detail_response = _detail_brokerage_authorization_with_retry(
                    client=client,
                    authorization_id=authorization_id,
                    user_id=snaptrade_user_id,
                    user_secret=user_secret,
                )
                detail = detail_response.body if hasattr(detail_response, "body") else detail_response
                if hasattr(detail, "to_dict"):
                    detail = detail.to_dict()
                if isinstance(detail, dict):
                    connection_type = detail.get("type") or detail.get("connection_type") or connection_type
                    disabled = bool(detail.get("disabled", False))
                    disabled_date = detail.get("disabled_date")

                    brokerage = detail.get("brokerage")
                    if isinstance(brokerage, dict):
                        brokerage_name = brokerage.get("name") or brokerage_name
                    brokerage_name = detail.get("brokerage_name") or brokerage_name
            except Exception as detail_error:
                log_error(
                    "snaptrade_connection",
                    "health_check_detail_brokerage_authorization",
                    detail_error,
                )

            probe_account_id = entry.get("probe_account_id")
            data_ok = False
            if probe_account_id:
                try:
                    _get_user_account_balance_with_retry(
                        client=client,
                        user_id=snaptrade_user_id,
                        user_secret=user_secret,
                        account_id=probe_account_id,
                    )
                    data_ok = True
                except Exception as balance_error:
                    log_error("snaptrade_connection", "health_check_get_user_account_balance", balance_error)

            trading_ok = None
            trading_error = None
            if probe_trading and probe_account_id:
                try:
                    _symbol_search_user_account_with_retry(
                        client=client,
                        user_id=snaptrade_user_id,
                        user_secret=user_secret,
                        account_id=probe_account_id,
                        substring="AAPL",
                    )
                    trading_ok = True
                except Exception as trading_probe_error:
                    trading_ok = False
                    trading_error = str(trading_probe_error)
                    log_error(
                        "snaptrade_connection",
                        "health_check_symbol_search_user_account",
                        trading_probe_error,
                    )

            health_results.append(
                {
                    "authorization_id": str(authorization_id),
                    "brokerage_name": brokerage_name,
                    "connection_type": connection_type,
                    "disabled": disabled,
                    "disabled_date": disabled_date,
                    "account_ids": entry.get("account_ids", []),
                    "data_ok": data_ok,
                    "trading_ok": trading_ok,
                    "trading_error": trading_error,
                }
            )

        return health_results

    except Exception as e:
        log_error("snaptrade_connection", "check_connection_health", e)
        return []


def remove_snaptrade_connection(user_email: str, authorization_id: str, client: SnapTrade):
    """
    Remove a specific SnapTrade brokerage connection.
    
    Args:
        user_email: User email address
        authorization_id: SnapTrade authorization ID to remove
        client: Initialized SnapTrade client
    """
    try:
        # Generate SnapTrade user ID from email (privacy-friendly)
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]
        user_secret = get_snaptrade_user_secret(user_email)
        
        if not user_secret:
            raise ValueError(f"No SnapTrade user secret found for {user_email}")
            
        # Remove the authorization
        client.connections.remove_brokerage_authorization(
            user_id=snaptrade_user_id,
            user_secret=user_secret,
            authorization_id=authorization_id
        )
        
        portfolio_logger.info(f"✅ Removed SnapTrade connection: {authorization_id}")
        
    except Exception as e:
        log_error("snaptrade_connection", "remove_connection", e)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# 🔄 TYPE MAPPING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _map_snaptrade_code_to_internal(snaptrade_code: str) -> str:
    """
    Map SnapTrade's standardized type codes using centralized mappings.
    
    CENTRALIZED MAPPING SYSTEM:
    Uses the established 3-tier architecture pattern (Database → YAML → Hardcoded)
    that is consistent with all other mapping systems in the risk module.
    
    THREE-LAYER TYPE SYSTEM:
    1. SnapTrade Raw: type.code ("cs") + type.description ("Common Stock")
    2. This Function: Maps code → internal type ("cs" → "equity") via centralized system
    3. Our System: Uses internal type for logic (cash mapping, database storage)
    
    SUPPORTED MAPPINGS (via centralized system):
    - cs/ps/ad/ut/wi → "equity" (Common/Preferred Stock, ADR, Unit, When Issued)
    - et → "etf" (ETF)
    - oef/cef → "mutual_fund" (Open/Closed End Fund)
    - bnd → "bond" (Bond)
    - crypto → "crypto" (Cryptocurrency)
    - rt/wt → "warrant" (Rights/Warrants)
    - struct → "derivative" (Structured Product)
    - cash → "cash" (Cash Balance - special case)
    
    CASH SPECIAL CASE:
    - Cash balances don't have type.code in SnapTrade API
    - We manually assign "cash" code in fetch_snaptrade_holdings()
    - This function maps "cash" → "cash" for consistency
    
    ARCHITECTURE:
    Calls utils.security_type_mappings.map_snaptrade_code() which uses:
    1. Database: security_type_mappings table (primary)
    2. YAML: security_type_mappings.yaml (fallback)
    3. Hardcoded: Built-in mapping dictionary (ultimate fallback)
    
    Args:
        snaptrade_code: SnapTrade standardized type code (cs, et, bnd, cash, etc.)
        
    Returns:
        Our internal type classification (equity, etf, cash, etc.)
        Preserves original code if unknown to maintain provider expertise
    """
    from utils.security_type_mappings import map_snaptrade_code
    
    # Use centralized mapping system
    mapped_type = map_snaptrade_code(snaptrade_code)
    if mapped_type:
        portfolio_logger.debug(f"✅ SnapTrade centralized mapping: {snaptrade_code} → {mapped_type}")
        return mapped_type
    else:
        # Log unknown code and return the original code as-is to preserve provider expertise
        portfolio_logger.warning(f"⚠️ Unknown SnapTrade code '{snaptrade_code}', using as-is")
        return snaptrade_code.lower()

# Asset class mapping function moved to SecurityTypeService._map_security_type_to_asset_class()
# for cleaner architecture and centralized logic


# ═══════════════════════════════════════════════════════════════════════════════
# 💼 HOLDINGS AND PORTFOLIO FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_snaptrade_holdings(user_email: str, client: SnapTrade) -> List[Dict]:
    """
    Fetch all holdings for a SnapTrade user across all their accounts.
    
    Uses a hybrid approach as recommended by SnapTrade:
    1. get_user_account_positions for securities (includes type mapping)
    2. get_user_account_balance for cash balances
    3. Combines both into unified holdings list
    
    TYPE MAPPING SYSTEM:
    - Extracts SnapTrade's raw type.code ("cs", "et", etc.) and type.description
    - Maps to our internal security_type using _map_snaptrade_code_to_internal()
    - Preserves all three fields for transparency and debugging
    
    CASH HANDLING:
    - Cash positions get special treatment:
      * snaptrade_type_code: "cash"
      * snaptrade_type_description: "Cash Balance"
      * security_type: "cash"
    - Cash will later be mapped to SGOV proxy for risk analysis
    
    Args:
        user_email: User email address
        client: Initialized SnapTrade client
        
    Returns:
        List of holdings dictionaries with position data (securities + cash)
        Each dict includes: ticker, quantity, value, currency, name, account_id,
        snaptrade_type_code, snaptrade_type_description, security_type
    """
    from utils.ticker_resolver import resolve_fmp_ticker

    try:
        # Generate SnapTrade user ID from email (privacy-friendly)
        snaptrade_user_id = get_snaptrade_user_id_from_email(user_email)
        user_hash = hashlib.sha256(snaptrade_user_id.encode()).hexdigest()[:16]
        user_secret = get_snaptrade_user_secret(user_email)
        
        if not user_secret:
            raise ValueError(f"No SnapTrade user secret found for {user_email}")
            
        # Get all user accounts first (with retry logic)
        try:
            accounts_response = _list_user_accounts_with_retry(client, snaptrade_user_id, user_secret)
        except ApiException as e:
            if not is_snaptrade_secret_error(e):
                raise

            failed_secret = user_secret
            lock = _get_rotation_lock(user_email)
            with lock:
                current_secret = get_snaptrade_user_secret(user_email)
                if current_secret != failed_secret:
                    portfolio_logger.info(
                        "SnapTrade secret already rotated by another caller for user_id=%s",
                        snaptrade_user_id,
                    )
                else:
                    rotate_snaptrade_user_secret(user_email, client)

            user_secret = get_snaptrade_user_secret(user_email)
            if not user_secret:
                raise ValueError(f"No SnapTrade user secret found for {user_email}")

            accounts_response = _list_user_accounts_with_retry(client, snaptrade_user_id, user_secret)
        
        # Extract accounts from API response
        accounts = accounts_response.body if hasattr(accounts_response, 'body') else accounts_response
        
        all_holdings = []
        
        # Process each account
        for account in accounts:
            account_id = account.get('id')
            account_name = account.get('name', 'Unknown Account')
            brokerage_name = account.get('institution_name', 'Unknown')
            
            # 1. Get securities positions (SnapTrade recommended endpoint) (with retry logic)
            try:
                positions_response = _get_user_account_positions_with_retry(
                    client, snaptrade_user_id, user_secret, account_id
                )
                
                # Extract positions from API response
                positions = positions_response.body if hasattr(positions_response, 'body') else positions_response
                
                # Process each securities position
                for position in positions:
                    # SnapTrade returns nested symbol structure as dictionaries
                    symbol_data = position.get('symbol', {})
                    inner_symbol = symbol_data.get('symbol', {}) if symbol_data else {}
                    
                    # Extract SnapTrade's raw type information
                    snaptrade_type_info = inner_symbol.get('type', {})
                    snaptrade_type_code = snaptrade_type_info.get('code', 'unknown') if snaptrade_type_info else 'unknown'
                    snaptrade_type_description = snaptrade_type_info.get('description', 'Unknown') if snaptrade_type_info else 'Unknown'
                    
                    # Map SnapTrade types to our internal type system using SecurityTypeService
                    raw_ticker = inner_symbol.get('symbol', 'UNKNOWN')
                    # IBKR-sourced symbols via SnapTrade can have trailing dots (e.g., "AT." for LSE stocks).
                    # Strip before resolution to avoid double-dot FMP symbols like "AT..L".
                    ticker = raw_ticker.rstrip(".") if raw_ticker and raw_ticker != "UNKNOWN" else raw_ticker
                    if not ticker or ticker == "UNKNOWN":
                        log_error(
                            "snaptrade_holdings",
                            "missing_ticker_symbol",
                            {
                                "account_id": account_id,
                                "account_name": account_name,
                                "brokerage_name": brokerage_name,
                                "security_description": inner_symbol.get("description"),
                                "snaptrade_type_code": snaptrade_type_code,
                                "snaptrade_type_description": snaptrade_type_description,
                            },
                        )
                    fallback_type = _map_snaptrade_code_to_internal(snaptrade_type_code)
                    our_security_type = get_enhanced_security_type(ticker, fallback_type)
                    
                    # Calculate cost basis from average_purchase_price (None if not available)
                    avg_purchase_price = position.get('average_purchase_price')
                    units = position.get('units')
                    if avg_purchase_price is not None and units is not None:
                        cost_basis = float(avg_purchase_price) * float(units)
                    else:
                        cost_basis = None

                    # Extract exchange MIC code (ISO-10383) for proper ticker resolution
                    exchange_data = inner_symbol.get('exchange', {})
                    exchange_mic = exchange_data.get('mic_code') if exchange_data else None

                    currency_code = inner_symbol.get('currency', {}).get('code', 'USD') if inner_symbol.get('currency') else "USD"

                    fmp_ticker = None
                    if ticker and ticker != "UNKNOWN" and our_security_type != "cash" and not ticker.startswith("CUR:"):
                        fmp_ticker = resolve_fmp_ticker(
                            ticker=ticker,
                            company_name=inner_symbol.get('description', 'Unknown Security'),
                            currency=currency_code,
                            exchange_mic=exchange_mic,
                        )
                    else:
                        fmp_ticker = ticker

                    position_data = {
                        "account_id": account_id,
                        "account_name": account_name,
                        "brokerage_name": brokerage_name,
                        "ticker": ticker,
                        "figi": inner_symbol.get("figi_code"),
                        "fmp_ticker": fmp_ticker,
                        "name": inner_symbol.get('description', 'Unknown Security'),
                        "quantity": float(position.get('units', 0) or 0),
                        "price": float(position.get('price', 0) or 0),
                        "market_value": float(position.get('units', 0) or 0) * float(position.get('price', 0) or 0),
                        "currency": currency_code,
                        "snaptrade_type_code": snaptrade_type_code,  # SnapTrade standardized code (cs, et, etc.)
                        "snaptrade_type_description": snaptrade_type_description,  # SnapTrade full description
                        "security_type": our_security_type,  # Our internal type mapping
                        "cost_basis": cost_basis,  # Total cost basis (avg_purchase_price × units)
                        "exchange_mic": exchange_mic,  # ISO-10383 Market Identifier Code (e.g., "XLON" for London)
                    }
                    
                    all_holdings.append(position_data)
                    
            except Exception as e:
                log_error("snaptrade_holdings", f"fetch_positions_account_{account_id}", e)
                # Continue to next account if positions fail
            
            # 2. Get cash balances for this account (with retry logic)
            try:
                balances_response = _get_user_account_balance_with_retry(
                    client, snaptrade_user_id, user_secret, account_id
                )
                
                # Extract balances from API response
                balances = balances_response.body if hasattr(balances_response, 'body') else balances_response
                
                # Process each cash balance
                for balance in balances:
                    # SnapTrade returns balance data as dictionaries
                    currency_info = balance.get('currency', {})
                    currency_code = currency_info.get('code', 'USD') if currency_info else 'USD'
                    cash_value = float(balance.get('cash', 0) or 0)
                    
                    # Only add non-zero cash balances
                    if cash_value != 0:
                        cash_data = {
                            "account_id": account_id,
                            "account_name": account_name,
                            "brokerage_name": brokerage_name,
                            "ticker": f"CUR:{currency_code}",  # Use currency prefix for cash
                            "fmp_ticker": f"CUR:{currency_code}",
                            "name": f"{currency_code} Cash",
                            "quantity": cash_value,  # For cash, quantity = value
                            "price": 1.0,  # Cash price is always 1.0
                            "market_value": cash_value,
                            "currency": currency_code,
                            "snaptrade_type_code": "cash",  # No SnapTrade code for balances (our designation)
                            "snaptrade_type_description": "Cash Balance",  # SnapTrade doesn't provide type for balances
                            "security_type": "cash"  # Our internal type for cash positions
                        }
                        all_holdings.append(cash_data)
                            
            except Exception as e:
                log_error("snaptrade_holdings", f"fetch_balances_account_{account_id}", e)
                # Continue to next account if balances fail
                
        return all_holdings
        
    except Exception as e:
        log_error("snaptrade_holdings", "fetch_holdings", e)
        raise


def normalize_snaptrade_holdings(holdings: List[Dict]) -> pd.DataFrame:
    """
    Convert processed SnapTrade holdings into a clean DataFrame.
    
    Takes the output from fetch_snaptrade_holdings (which already handles the complex 
    API structure and type mapping) and creates a clean DataFrame ready for consolidation.
    
    TYPE PRESERVATION:
    - Preserves all type fields from fetch_snaptrade_holdings:
      * snaptrade_type_code: SnapTrade's raw codes ("cs", "et", "cash")
      * snaptrade_type_description: Human-readable descriptions
      * security_type: Our internal classification ("equity", "etf", "cash")
    
    DATA CLEANING:
    - Renames 'market_value' to 'value' for consistency
    - Ensures numeric columns are properly typed
    - No filtering of derivatives (SnapTrade handles options separately)
    
    Note: SnapTrade separates securities and options into different endpoints, so this
    function only handles securities (stocks, ETFs, crypto, mutual funds) and cash.
    Options are handled via a separate snaptrade.options.list_option_holdings endpoint.
    
    Args:
        holdings: List of processed holdings dictionaries from fetch_snaptrade_holdings
        
    Returns:
        DataFrame with clean holdings data ready for consolidation
    """
    if not holdings:
        return pd.DataFrame()
        
    try:
        # Convert to DataFrame - fetch_snaptrade_holdings already did the heavy lifting
        df = pd.DataFrame(holdings)
        
        # Rename market_value to value for consistency with Plaid format
        if 'market_value' in df.columns:
            df = df.rename(columns={'market_value': 'value'})
        
        # Ensure numeric columns are properly typed
        numeric_columns = ['quantity', 'value', 'price']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        return df
        
    except Exception as e:
        log_error("snaptrade_holdings", "normalize_holdings", e)
        raise


def consolidate_snaptrade_holdings(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """
    Consolidate normalized SnapTrade holdings by ticker across multiple accounts.

    CONSOLIDATION LOGIC:
    - Sums quantity and value for each unique ticker (or ticker+currency for non-cash)
    - Preserves ALL metadata fields from first occurrence (matches Plaid behavior)
    - Uses sum + first-row join pattern for complete metadata preservation

    PRESERVED FIELDS:
    - All type fields: snaptrade_type_code, snaptrade_type_description, security_type
    - Account info: account_id, account_name, brokerage_name
    - Position data: name, price, cost_basis, currency

    Consolidation rules:
    - Cash: consolidate by currency key (CUR:USD, CUR:CAD, etc.)
    - Non-cash: consolidate by ticker AND currency (keeps multi-currency separate)

    Args:
        holdings_df: DataFrame with normalized SnapTrade holdings (from normalize_snaptrade_holdings)

    Returns:
        DataFrame with consolidated positions, all metadata preserved from first occurrence
    """
    if holdings_df.empty:
        return holdings_df

    try:
        # Separate cash and non-cash positions
        cash_mask = holdings_df['ticker'].str.startswith('CUR:', na=False)
        cash_positions = holdings_df[cash_mask].copy()
        non_cash_positions = holdings_df[~cash_mask].copy()

        consolidated_positions = []

        # 1. Consolidate cash positions by ticker (currency key like CUR:USD)
        if not cash_positions.empty:
            if "local_value" not in cash_positions.columns:
                cash_positions["local_value"] = cash_positions.get("value")
            # Sum numeric columns (include cost_basis if present)
            sum_cols = ['quantity', 'value', 'local_value']
            if 'cost_basis' in cash_positions.columns:
                sum_cols.append('cost_basis')
            sums = (
                cash_positions
                .groupby('ticker', as_index=False)[sum_cols]
                .sum()
            )

            # Get first row per ticker for ALL metadata (matches Plaid pattern)
            firsts = (
                cash_positions
                .sort_values('ticker')
                .drop_duplicates('ticker', keep='first')
                .set_index('ticker')
            )
            # Drop summed columns from firsts to avoid duplication
            drop_cols = ['quantity', 'value', 'local_value']
            if 'cost_basis' in firsts.columns:
                drop_cols.append('cost_basis')

            # Join sums with metadata
            cash_consolidated = (
                sums.set_index('ticker')
                .join(firsts.drop(columns=drop_cols, errors='ignore'), how='left')
                .reset_index()
            )
            consolidated_positions.append(cash_consolidated)

        # 2. Consolidate non-cash positions by ticker AND currency
        # This naturally handles mixed currencies without special logic
        if not non_cash_positions.empty:
            if "local_price" not in non_cash_positions.columns:
                non_cash_positions["local_price"] = non_cash_positions.get("price")
            if "local_value" not in non_cash_positions.columns:
                non_cash_positions["local_value"] = non_cash_positions.get("value")
            # Sum numeric columns grouped by ticker + currency
            # IMPORTANT: Include cost_basis in sum, not just quantity/value
            sum_cols = ['quantity', 'value', 'local_value']
            if 'cost_basis' in non_cash_positions.columns:
                sum_cols.append('cost_basis')
            sums = (
                non_cash_positions
                .groupby(['ticker', 'currency'], as_index=False)[sum_cols]
                .sum()
            )

            # Get first row per ticker+currency for ALL metadata
            firsts = (
                non_cash_positions
                .sort_values(['ticker', 'currency'])
                .drop_duplicates(['ticker', 'currency'], keep='first')
                .set_index(['ticker', 'currency'])
            )
            # Drop cost_basis from firsts since we're summing it
            if 'cost_basis' in firsts.columns:
                firsts = firsts.drop(columns=['cost_basis'])

            # Join sums with metadata
            non_cash_consolidated = (
                sums.set_index(['ticker', 'currency'])
                .join(firsts.drop(columns=['quantity', 'value', 'local_value'], errors='ignore'), how='left')
                .reset_index()
            )
            consolidated_positions.append(non_cash_consolidated)

        # Combine all consolidated positions
        if consolidated_positions:
            result_df = pd.concat(consolidated_positions, ignore_index=True)
            return result_df
        else:
            return pd.DataFrame()

    except Exception as e:
        log_error("snaptrade_holdings", "consolidate_holdings", e)
        raise


def get_enhanced_security_type(ticker: str, original_type: str) -> str:
    """
    Get security type with cash preservation and FMP enhancement.
    
    ENHANCEMENT: This function implements the cash-first strategy to fix security type
    classification inconsistencies (like DSU being "equity" vs "mutual_fund").
    
    STRATEGY:
    1. Cash positions: Trust SnapTrade's classification (they know banking/currency)
    2. Securities: Use SecurityTypeService with FMP API only if it finds data, otherwise keep original
    3. No hardcoded fallbacks: Preserves original provider types when SecurityTypeService has no data
    
    PROBLEM SOLVED:
    - Before: DSU classified as "equity" by SnapTrade → 80% crash scenario
    - After: DSU classified as "mutual_fund" by FMP → 40% crash scenario
    - No hardcoded fallbacks - preserves original provider types when SecurityTypeService has no data
    
    Args:
        ticker: Security ticker symbol (e.g., 'DSU', 'SPY', 'AAPL')
        original_type: Original security type from SnapTrade provider
        
    Returns:
        Enhanced security type or original type if SecurityTypeService has no data
        
    Examples:
        >>> get_enhanced_security_type('DSU', 'equity')
        'mutual_fund'  # FMP corrects SnapTrade classification
        >>> get_enhanced_security_type('CUR:USD', 'cash') 
        'cash'  # Cash preserved from provider
        >>> get_enhanced_security_type('UNKNOWN_TICKER', 'derivative')
        'derivative'  # Original type preserved when SecurityTypeService has no data
    """
    if original_type == 'cash':
        portfolio_logger.debug(f"💰 Preserving SnapTrade cash classification for {ticker}: {original_type}")
        return 'cash'  # ✅ Preserve provider cash classification
    
    portfolio_logger.debug(f"🔍 SnapTrade classified {ticker} as '{original_type}' - enhancing with FMP lookup")
    
    try:
        from services.security_type_service import SecurityTypeService
        
        # Use SecurityTypeService static method for non-cash securities (takes list of tickers)
        security_types = SecurityTypeService.get_security_types([ticker])
        enhanced_type = security_types.get(ticker)  # Don't pass fallback - let it be None if not found
        
        # If SecurityTypeService found a classification, use it; otherwise keep original
        if enhanced_type:
            # Log when enhancement changes the classification
            if enhanced_type != original_type:
                portfolio_logger.info(f"✨ SecurityTypeService enhanced {ticker}: {original_type} → {enhanced_type}")
            else:
                portfolio_logger.debug(f"✅ FMP confirmed {ticker} SnapTrade classification: {enhanced_type}")
            return enhanced_type
        else:
            # SecurityTypeService had no data - keep original provider type
            portfolio_logger.warning(f"⚠️ FMP has no data for {ticker}, keeping SnapTrade classification: {original_type}")
            return original_type
        
    except ImportError as e:
        portfolio_logger.error(f"❌ SecurityTypeService import failed for {ticker}: {e}, using SnapTrade type: {original_type}")
        return original_type
    except Exception as e:
        portfolio_logger.error(f"❌ SecurityTypeService failed for {ticker}: {e}, falling back to SnapTrade type: {original_type}")
        return original_type


def convert_snaptrade_holdings_to_portfolio_data(holdings_df: pd.DataFrame, user_email: str, 
                                               portfolio_name: str = "CURRENT_PORTFOLIO"):
    """
    Convert SnapTrade holdings DataFrame to PortfolioData object.
    
    CASH vs SECURITIES HANDLING:
    - Cash positions (security_type='cash'): Stored as {'dollars': value}
    - Securities: Stored as {'shares': quantity} (allows negative for shorts)
    - Uses preserved security_type field from consolidation (no ticker pattern matching)
    
    MIXED CURRENCY HANDLING:
    - Database stores separate rows correctly (ticker + currency consolidation)
    - PortfolioData sums shares across currencies (currency ignored by analysis)
    - Currency field set to 'MIXED' when consolidating across different currencies
    - First currency preserved for single-currency positions
    - Logs mixed currency summing for transparency
    - No ticker mutation (preserves clean tickers for factor mapping)
    
    TYPE SYSTEM INTEGRATION:
    - Relies on security_type field preserved through the entire pipeline:
      fetch → normalize → consolidate → convert
    - Cash positions will later be mapped CUR:USD → SGOV by portfolio_manager
    - All position types properly identified for database storage
    - Persists name/brokerage_name/account_name for cache fidelity
    
    Args:
        holdings_df: DataFrame with normalized SnapTrade holdings
        user_email: User's email for metadata
        portfolio_name: Portfolio name for database storage
        
    Returns:
        PortfolioData object ready for database storage
    """
    try:
        from portfolio_risk_engine.data_objects import PortfolioData
        
        if holdings_df.empty:
            # Return empty portfolio using from_holdings method
            return PortfolioData.from_holdings(
                holdings={},
                start_date=PORTFOLIO_DEFAULTS["start_date"],
                end_date=PORTFOLIO_DEFAULTS["end_date"],
                portfolio_name=portfolio_name,
                expected_returns={}
            )
        
        # IMPORTANT: Consolidate holdings by ticker first (like Plaid does)
        # This handles multiple accounts with the same ticker
        consolidated_df = consolidate_snaptrade_holdings(holdings_df)
        
        # Convert consolidated DataFrame to holdings dictionary format expected by PortfolioData.from_holdings
        # Mirror Plaid conversion pattern: cash as dollars, non-cash as shares (allow negatives for shorts)
        holdings_dict = {}
        fmp_ticker_map = {}
        
        # Track mixed currencies for logging
        ticker_currencies = {}
        for _, row in consolidated_df.iterrows():
            ticker = row.get('ticker', 'UNKNOWN')
            currency = row.get('currency', 'USD')
            
            if ticker not in ticker_currencies:
                ticker_currencies[ticker] = set()
            ticker_currencies[ticker].add(currency)
        
        # Log mixed currency info (now summing instead of overwriting)
        for ticker, currencies in ticker_currencies.items():
            if len(currencies) > 1:
                log_error("snaptrade_portfolio_conversion", "mixed_currency_summing", {
                    "ticker": ticker,
                    "currencies": list(currencies),
                    "message": f"Mixed currencies for {ticker}: {currencies}. Summing shares across currencies for PortfolioData (currency ignored by analysis)",
                    "behavior": "sum_shares"
                })
        
        # Process each holding - sum shares for same ticker across currencies
        for _, row in consolidated_df.iterrows():
            ticker = row.get('ticker', 'UNKNOWN')
            quantity = float(row.get('quantity', 0))
            value = float(row.get('value', 0))
            currency = row.get('currency', 'USD')
            cost_basis = row.get('cost_basis')  # Extract cost_basis for DB storage
            account_id = row.get('account_id')  # Extract account_id for DB storage
            name = row.get('name') or ticker
            brokerage_name = row.get('brokerage_name')
            account_name = row.get('account_name')
            fmp_ticker = row.get('fmp_ticker')
            # Use security_type from DataFrame (already enhanced in fetch_snaptrade_holdings)
            position_type = row.get('security_type')  # NO hardcoded fallback

            if isinstance(fmp_ticker, str) and fmp_ticker.strip():
                existing_fmp = fmp_ticker_map.get(ticker)
                if existing_fmp and existing_fmp != fmp_ticker:
                    raise ValueError(f"Conflicting fmp_ticker for {ticker}: {existing_fmp} vs {fmp_ticker}")
                fmp_ticker_map[ticker] = fmp_ticker

            # Handle cash positions (store as dollars, not shares)
            if position_type == 'cash':
                if ticker in holdings_dict:
                    # Sum cash values across currencies
                    holdings_dict[ticker]['dollars'] += float(value)
                    if not holdings_dict[ticker].get('name') and name:
                        holdings_dict[ticker]['name'] = name
                    if not holdings_dict[ticker].get('brokerage_name') and brokerage_name:
                        holdings_dict[ticker]['brokerage_name'] = brokerage_name
                    if not holdings_dict[ticker].get('account_name') and account_name:
                        holdings_dict[ticker]['account_name'] = account_name
                    # Mark as mixed if currencies differ
                    existing_currency = holdings_dict[ticker].get('currency')
                    if existing_currency != currency:
                        holdings_dict[ticker]['currency'] = 'MIXED'
                    if fmp_ticker_map.get(ticker) and 'fmp_ticker' not in holdings_dict[ticker]:
                        holdings_dict[ticker]['fmp_ticker'] = fmp_ticker_map[ticker]
                else:
                    holdings_dict[ticker] = {
                        'dollars': float(value),  # Store as dollars, not shares
                        'currency': currency,
                        'type': 'cash',
                        'account_id': account_id,
                        'name': name,
                        'brokerage_name': brokerage_name,
                        'account_name': account_name
                    }
                    if fmp_ticker_map.get(ticker):
                        holdings_dict[ticker]['fmp_ticker'] = fmp_ticker_map[ticker]
            else:
                # Handle non-cash positions - sum shares across currencies
                if ticker in holdings_dict:
                    # Sum shares (currency doesn't matter for PortfolioData analysis)
                    holdings_dict[ticker]['shares'] += float(quantity)
                    # Sum cost_basis when consolidating same ticker
                    # Use pd.notna() to catch both None and NaN (NaN + x = NaN would poison the sum)
                    if pd.notna(cost_basis):
                        existing_cost = holdings_dict[ticker].get('cost_basis')
                        if pd.notna(existing_cost):
                            holdings_dict[ticker]['cost_basis'] = existing_cost + cost_basis
                        else:
                            holdings_dict[ticker]['cost_basis'] = cost_basis
                    else:
                        # Warn about missing cost_basis (not expected for non-cash positions)
                        log_error("snaptrade_portfolio_conversion", "missing_cost_basis", {
                            "ticker": ticker,
                            "message": f"Missing cost_basis for {ticker} (None or NaN)"
                        })
                    # Mark as mixed if currencies differ
                    existing_currency = holdings_dict[ticker].get('currency')
                    if existing_currency != currency:
                        holdings_dict[ticker]['currency'] = 'MIXED'
                    # Use already-enhanced security type from DataFrame
                    holdings_dict[ticker]['type'] = position_type
                    if not holdings_dict[ticker].get('name') and name:
                        holdings_dict[ticker]['name'] = name
                    if not holdings_dict[ticker].get('brokerage_name') and brokerage_name:
                        holdings_dict[ticker]['brokerage_name'] = brokerage_name
                    if not holdings_dict[ticker].get('account_name') and account_name:
                        holdings_dict[ticker]['account_name'] = account_name
                    if fmp_ticker_map.get(ticker) and 'fmp_ticker' not in holdings_dict[ticker]:
                        holdings_dict[ticker]['fmp_ticker'] = fmp_ticker_map[ticker]
                else:
                    # Use already-enhanced security type from DataFrame
                    holdings_dict[ticker] = {
                        'shares': float(quantity),  # Allow negative and fractional shares
                        'currency': row.get('currency', 'USD'),  # Preserve currency from SnapTrade
                        'type': position_type,  # Already enhanced in fetch_snaptrade_holdings
                        'cost_basis': cost_basis,
                        'account_id': account_id,
                        'name': name,
                        'brokerage_name': brokerage_name,
                        'account_name': account_name
                    }
                    if fmp_ticker_map.get(ticker):
                        holdings_dict[ticker]['fmp_ticker'] = fmp_ticker_map[ticker]
        
        # Create PortfolioData object using the standard from_holdings method
        portfolio_data = PortfolioData.from_holdings(
            holdings=holdings_dict,
            start_date=PORTFOLIO_DEFAULTS["start_date"],
            end_date=PORTFOLIO_DEFAULTS["end_date"],
            portfolio_name=portfolio_name,
            expected_returns={},
            fmp_ticker_map=fmp_ticker_map or None,
        )
        
        # Add metadata (matching Plaid pattern)
        from datetime import datetime
        portfolio_data.import_source = 'snaptrade'
        portfolio_data.import_date = datetime.now().isoformat()
        portfolio_data.user_email = user_email
        
        return portfolio_data
        
    except Exception as e:
        log_error("snaptrade_portfolio", "convert_to_portfolio_data", e)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# 📊 ERROR HANDLING AND RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

def handle_snaptrade_api_exception(e: ApiException, operation: str) -> bool:
    """
    Handle SnapTrade API exceptions with appropriate retry logic.
    
    Args:
        e: SnapTrade API exception
        operation: Operation name for logging
        
    Returns:
        True if operation should be retried, False otherwise
    """
    try:
        status_code = e.status
        
        # Map errors according to plan requirements
        if status_code in [401, 403]:
            # Authentication/authorization errors - no retry
            log_error("snaptrade_api", operation, {
                "error_type": "auth_error",
                "status_code": status_code,
                "message": str(e),
                "retry": False
            })
            return False
            
        elif status_code == 429:
            # Rate limit - retry with backoff
            log_error("snaptrade_api", operation, {
                "error_type": "rate_limit",
                "status_code": status_code,
                "message": str(e),
                "retry": True
            })
            return True
            
        elif status_code >= 500:
            # Server errors - retry
            log_error("snaptrade_api", operation, {
                "error_type": "server_error",
                "status_code": status_code,
                "message": str(e),
                "retry": True
            })
            return True
            
        elif status_code >= 400:
            # Other client errors - no retry
            log_error("snaptrade_api", operation, {
                "error_type": "client_error",
                "status_code": status_code,
                "message": str(e),
                "retry": False
            })
            return False
            
        else:
            # Unknown error - no retry to be safe
            log_error("snaptrade_api", operation, {
                "error_type": "unknown_error",
                "status_code": status_code,
                "message": str(e),
                "retry": False
            })
            return False
            
    except Exception as parse_error:
        log_error("snaptrade_api", "error_parsing", parse_error)
        return False


def with_snaptrade_retry(operation_name: str, max_retries: int = 3):
    """
    Retry decorator for SnapTrade API calls using existing error classification.
    
    Uses handle_snaptrade_api_exception() to determine if errors should be retried.
    Implements exponential backoff for retryable errors (429, 5xx).
    
    Args:
        operation_name: Name of the operation for logging
        max_retries: Maximum number of retry attempts (default: 3)
        
    Returns:
        Decorator function that wraps SnapTrade API calls with retry logic
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except ApiException as e:
                    last_exception = e
                    should_retry = handle_snaptrade_api_exception(e, f"{operation_name}_attempt_{attempt + 1}")
                    
                    if not should_retry or attempt == max_retries:
                        # Don't retry or max attempts reached
                        portfolio_logger.error(f"❌ {operation_name} failed after {attempt + 1} attempts")
                        raise e
                    
                    # Calculate exponential backoff delay
                    delay = 2 ** attempt  # 1s, 2s, 4s
                    portfolio_logger.warning(f"⏳ {operation_name} attempt {attempt + 1} failed, retrying in {delay}s...")
                    
                    import time
                    time.sleep(delay)
                    
                except Exception as e:
                    # Non-API exceptions (network, etc.) - don't retry
                    portfolio_logger.error(f"❌ {operation_name} failed with non-API error: {e}")
                    raise e
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            else:
                raise Exception(f"Unknown error in {operation_name} after {max_retries + 1} attempts")
                
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# 🔄 RETRY-WRAPPED API CALLS
# ═══════════════════════════════════════════════════════════════════════════════

@with_snaptrade_retry("register_snap_trade_user")
def _register_snap_trade_user_with_retry(client: SnapTrade, user_id: str):
    """Register user with SnapTrade API with retry logic."""
    return client.authentication.register_snap_trade_user(user_id=user_id)

@with_snaptrade_retry("login_snap_trade_user")
def _login_snap_trade_user_with_retry(
    client: SnapTrade,
    user_id: str,
    user_secret: str,
    broker=None,
    immediate_redirect=True,
    custom_redirect=None,
    connection_type: Optional[str] = None,
    reconnect: Optional[str] = None,
):
    """Create SnapTrade connection URL with retry logic."""
    kwargs: Dict[str, Any] = dict(
        user_id=user_id,
        user_secret=user_secret,
        broker=broker,
        immediate_redirect=immediate_redirect,
        custom_redirect=custom_redirect,
    )
    if connection_type is not None:
        kwargs["connection_type"] = connection_type
    if reconnect is not None:
        kwargs["reconnect"] = reconnect
    return client.authentication.login_snap_trade_user(**kwargs)

@with_snaptrade_retry("list_user_accounts")
def _list_user_accounts_with_retry(client: SnapTrade, user_id: str, user_secret: str):
    """List user accounts with retry logic."""
    return client.account_information.list_user_accounts(
        user_id=user_id,
        user_secret=user_secret
    )

@with_snaptrade_retry("detail_brokerage_authorization")
def _detail_brokerage_authorization_with_retry(
    client: SnapTrade,
    authorization_id: str,
    user_id: str,
    user_secret: str,
):
    """Get brokerage authorization details with retry logic."""
    return client.connections.detail_brokerage_authorization(
        authorization_id=authorization_id,
        user_id=user_id,
        user_secret=user_secret,
    )

@with_snaptrade_retry("get_user_account_positions")
def _get_user_account_positions_with_retry(client: SnapTrade, user_id: str, user_secret: str, account_id: str):
    """Get account positions with retry logic."""
    return client.account_information.get_user_account_positions(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id
    )

@with_snaptrade_retry("get_user_account_balance")
def _get_user_account_balance_with_retry(client: SnapTrade, user_id: str, user_secret: str, account_id: str):
    """Get account balance with retry logic."""
    return client.account_information.get_user_account_balance(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id
    )

@with_snaptrade_retry("remove_brokerage_authorization")
def _remove_brokerage_authorization_with_retry(client: SnapTrade, user_id: str, user_secret: str, authorization_id: str):
    """Remove brokerage authorization with retry logic."""
    return client.connections.remove_brokerage_authorization(
        user_id=user_id,
        user_secret=user_secret,
        authorization_id=authorization_id
    )

@with_snaptrade_retry("delete_snap_trade_user")
def _delete_snap_trade_user_with_retry(client: SnapTrade, user_id: str):
    """Delete SnapTrade user with retry logic."""
    return client.authentication.delete_snap_trade_user(user_id=user_id)

@with_snaptrade_retry("symbol_search_user_account")
def _symbol_search_user_account_with_retry(
    client: SnapTrade,
    user_id: str,
    user_secret: str,
    account_id: str,
    substring: str,
):
    """Search symbols supported by a specific account with retry logic."""
    return client.reference_data.symbol_search_user_account(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id,
        substring=substring,
    )

@with_snaptrade_retry("get_order_impact")
def _get_order_impact_with_retry(
    client: SnapTrade,
    user_id: str,
    user_secret: str,
    account_id: str,
    side: str,
    universal_symbol_id: str,
    order_type: str,
    time_in_force: str,
    quantity: float,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
):
    """Preview order impact with retry logic."""
    return client.trading.get_order_impact(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id,
        action=side,
        universal_symbol_id=universal_symbol_id,
        order_type=order_type,
        time_in_force=time_in_force,
        units=quantity,
        price=limit_price,
        stop=stop_price,
    )

@with_snaptrade_retry("place_order")
def _place_order_with_retry(
    client: SnapTrade,
    user_id: str,
    user_secret: str,
    trade_id: str,
    wait_to_confirm: bool = True,
):
    """Place a previously checked order with retry logic."""
    return client.trading.place_order(
        user_id=user_id,
        user_secret=user_secret,
        trade_id=trade_id,
        wait_to_confirm=wait_to_confirm,
    )

@with_snaptrade_retry("get_user_account_orders")
def _get_user_account_orders_with_retry(
    client: SnapTrade,
    user_id: str,
    user_secret: str,
    account_id: str,
    state: str = "all",
    days: int = 30,
):
    """List account orders with retry logic."""
    return client.account_information.get_user_account_orders(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id,
        state=state,
        days=days,
    )

@with_snaptrade_retry("cancel_order")
def _cancel_order_with_retry(
    client: SnapTrade,
    user_id: str,
    user_secret: str,
    account_id: str,
    brokerage_order_id: str,
):
    """Cancel a brokerage order with retry logic."""
    return client.trading.cancel_order(
        user_id=user_id,
        user_secret=user_secret,
        account_id=account_id,
        brokerage_order_id=brokerage_order_id,
    )


def _extract_snaptrade_body(response: Any) -> Any:
    """Unwrap SDK ApiResponse objects and return plain body payload."""
    if hasattr(response, "body"):
        return response.body
    return response


def _get_snaptrade_identity(user_email: str) -> tuple[str, str]:
    """Resolve SnapTrade user_id/user_secret pair from user email."""
    user_id = get_snaptrade_user_id_from_email(user_email)
    user_secret = get_snaptrade_user_secret(user_email)
    if not user_secret:
        raise ValueError(f"No SnapTrade user secret found for {user_email}")
    return user_id, user_secret


def _to_float(value: Any) -> Optional[float]:
    """Best-effort numeric conversion helper."""
    try:
        if value is None:
            return None
        result = float(value)
        if math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def search_snaptrade_symbol(
    user_email: str,
    account_id: str,
    ticker: str,
    client: Optional[SnapTrade] = None,
) -> Dict[str, Any]:
    """
    Search account-supported symbols and require exact ticker match.

    Returns the resolved universal_symbol_id and symbol metadata.
    """
    if not client:
        client = get_snaptrade_client()
    if not client:
        raise ValueError("SnapTrade client unavailable")

    try:
        user_id, user_secret = _get_snaptrade_identity(user_email)
        ticker_upper = (ticker or "").upper().strip()
        if not ticker_upper:
            raise ValueError("Ticker is required")

        response = _symbol_search_user_account_with_retry(
            client,
            user_id,
            user_secret,
            account_id,
            ticker_upper,
        )
        symbols = _extract_snaptrade_body(response) or []

        normalized: List[Dict[str, Any]] = []
        for item in symbols:
            entry = item if isinstance(item, dict) else {}
            symbol_value = entry.get("symbol")
            if isinstance(symbol_value, dict):
                symbol_text = (symbol_value.get("symbol") or "").upper().strip()
            else:
                symbol_text = str(symbol_value or "").upper().strip()
            normalized.append(
                {
                    "id": entry.get("id") or entry.get("universal_symbol_id"),
                    "symbol": symbol_text,
                    "raw_symbol": str(entry.get("raw_symbol") or "").upper().strip(),
                    "name": entry.get("description") or entry.get("name"),
                    "currency": entry.get("currency"),
                    "type": entry.get("type"),
                    "full": entry,
                }
            )

        exact_matches = [s for s in normalized if s.get("symbol") == ticker_upper]
        if not exact_matches:
            close_matches = [s.get("symbol") for s in normalized if s.get("symbol")]
            preview = ", ".join(close_matches[:8]) if close_matches else "none"
            raise ValueError(
                f"No exact symbol match for '{ticker_upper}' in account {account_id}. "
                f"Closest matches: {preview}"
            )

        exact = exact_matches[0]
        universal_symbol_id = exact.get("id")
        if not universal_symbol_id:
            raise ValueError(f"Exact symbol match for '{ticker_upper}' missing universal symbol id")

        return {
            "ticker": ticker_upper,
            "symbol": exact.get("symbol"),
            "universal_symbol_id": universal_symbol_id,
            "raw_symbol": exact.get("raw_symbol"),
            "name": exact.get("name"),
            "currency": exact.get("currency"),
            "type": exact.get("type"),
            "all_matches": normalized,
        }
    except Exception as e:
        log_error("snaptrade_trading", "search_symbol", e)
        raise


def preview_snaptrade_order(
    user_email: str,
    account_id: str,
    ticker: str,
    side: str,
    quantity: float,
    order_type: str = "Market",
    time_in_force: str = "Day",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    universal_symbol_id: Optional[str] = None,
    client: Optional[SnapTrade] = None,
) -> Dict[str, Any]:
    """
    Preview an order with SnapTrade get_order_impact and parsed computed fields.
    """
    if not client:
        client = get_snaptrade_client()
    if not client:
        raise ValueError("SnapTrade client unavailable")

    try:
        user_id, user_secret = _get_snaptrade_identity(user_email)
        side = (side or "").upper().strip()

        symbol_info = None
        resolved_symbol_id = universal_symbol_id
        if not resolved_symbol_id:
            symbol_info = search_snaptrade_symbol(
                user_email=user_email,
                account_id=account_id,
                ticker=ticker,
                client=client,
            )
            resolved_symbol_id = symbol_info["universal_symbol_id"]

        response = _get_order_impact_with_retry(
            client=client,
            user_id=user_id,
            user_secret=user_secret,
            account_id=account_id,
            side=side,
            universal_symbol_id=resolved_symbol_id,
            order_type=order_type,
            time_in_force=time_in_force,
            quantity=float(quantity),
            limit_price=_to_float(limit_price),
            stop_price=_to_float(stop_price),
        )

        impact = _extract_snaptrade_body(response) or {}
        trade = impact.get("trade") or {}
        trade_impacts = impact.get("trade_impacts") or []

        estimated_commission = 0.0
        for impact_row in trade_impacts:
            if isinstance(impact_row, dict):
                estimated_commission += _to_float(impact_row.get("estimated_commission")) or 0.0
                estimated_commission += _to_float(impact_row.get("forex_fees")) or 0.0

        estimated_price = _to_float(trade.get("price"))
        if estimated_price is None:
            estimated_price = _to_float(limit_price)
        if estimated_price is None:
            estimated_price = _to_float(stop_price)

        estimated_total = None
        if estimated_price is not None:
            estimated_total = (estimated_price * float(quantity)) + estimated_commission
        elif estimated_commission > 0:
            estimated_total = estimated_commission

        return {
            "account_id": account_id,
            "ticker": (ticker or "").upper().strip(),
            "side": side,
            "quantity": float(quantity),
            "order_type": order_type,
            "time_in_force": time_in_force,
            "limit_price": _to_float(limit_price),
            "stop_price": _to_float(stop_price),
            "universal_symbol_id": resolved_symbol_id,
            "symbol_info": symbol_info,
            "snaptrade_trade_id": trade.get("id"),
            "estimated_price": estimated_price,
            "estimated_commission": estimated_commission,
            "estimated_total": estimated_total,
            "combined_remaining_balance": impact.get("combined_remaining_balance"),
            "trade_impacts": trade_impacts,
            "impact_response": impact,
        }
    except Exception as e:
        log_error("snaptrade_trading", "preview_order", e)
        raise


def place_snaptrade_checked_order(
    user_email: str,
    snaptrade_trade_id: str,
    wait_to_confirm: bool = True,
    client: Optional[SnapTrade] = None,
) -> Dict[str, Any]:
    """Submit a previously previewed order by SnapTrade trade_id."""
    if not client:
        client = get_snaptrade_client()
    if not client:
        raise ValueError("SnapTrade client unavailable")

    try:
        user_id, user_secret = _get_snaptrade_identity(user_email)
        response = _place_order_with_retry(
            client=client,
            user_id=user_id,
            user_secret=user_secret,
            trade_id=snaptrade_trade_id,
            wait_to_confirm=wait_to_confirm,
        )
        return _extract_snaptrade_body(response) or {}
    except Exception as e:
        log_error("snaptrade_trading", "place_order", e)
        raise


def get_snaptrade_orders(
    user_email: str,
    account_id: str,
    state: str = "all",
    days: int = 30,
    client: Optional[SnapTrade] = None,
) -> List[Dict[str, Any]]:
    """Fetch account orders from account_information namespace."""
    if not client:
        client = get_snaptrade_client()
    if not client:
        raise ValueError("SnapTrade client unavailable")

    try:
        user_id, user_secret = _get_snaptrade_identity(user_email)
        response = _get_user_account_orders_with_retry(
            client=client,
            user_id=user_id,
            user_secret=user_secret,
            account_id=account_id,
            state=state,
            days=days,
        )
        orders = _extract_snaptrade_body(response) or []
        return orders if isinstance(orders, list) else [orders]
    except Exception as e:
        log_error("snaptrade_trading", "get_orders", e)
        raise


def cancel_snaptrade_order(
    user_email: str,
    account_id: str,
    order_id: str,
    client: Optional[SnapTrade] = None,
) -> Dict[str, Any]:
    """Cancel an existing brokerage order."""
    if not client:
        client = get_snaptrade_client()
    if not client:
        raise ValueError("SnapTrade client unavailable")

    try:
        user_id, user_secret = _get_snaptrade_identity(user_email)
        response = _cancel_order_with_retry(
            client=client,
            user_id=user_id,
            user_secret=user_secret,
            account_id=account_id,
            brokerage_order_id=order_id,
        )
        return _extract_snaptrade_body(response) or {}
    except Exception as e:
        log_error("snaptrade_trading", "cancel_order", e)
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 HIGH-LEVEL INTEGRATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def load_all_user_snaptrade_holdings(user_email: str, region_name: str = "us-east-1", 
                                    client: Optional[SnapTrade] = None) -> pd.DataFrame:
    """
    Load and consolidate all SnapTrade holdings for a user.
    
    COMPLETE PIPELINE EXECUTION:
    1. fetch_snaptrade_holdings: Hybrid API calls + type mapping
    2. normalize_snaptrade_holdings: Clean DataFrame with preserved types  
    3. consolidate_snaptrade_holdings: Sum by ticker, preserve type fields
    
    Result: Ready for convert_snaptrade_holdings_to_portfolio_data() with
    proper cash/securities distinction for database storage.
    
    Args:
        user_email: User email address
        region_name: AWS region for secrets
        client: Optional pre-initialized SnapTrade client
        
    Returns:
        DataFrame with consolidated holdings from all SnapTrade accounts
    """
    try:
        if not client:
            client = get_snaptrade_client(region_name)
            
        if not client:
            return pd.DataFrame()  # SnapTrade disabled or unavailable
            
        # Fetch raw holdings
        raw_holdings = fetch_snaptrade_holdings(user_email, client)
        
        if not raw_holdings:
            return pd.DataFrame()
            
        # Normalize holdings data
        holdings_df = normalize_snaptrade_holdings(raw_holdings)
        
        # Consolidate across accounts with currency guard
        consolidated_df = consolidate_snaptrade_holdings(holdings_df)
        
        log_portfolio_operation("snaptrade_load_holdings", {
            "user_email": user_email,
            "raw_holdings_count": len(raw_holdings),
            "consolidated_count": len(consolidated_df)
        })
        
        return consolidated_df
        
    except Exception as e:
        log_error("snaptrade_integration", "load_all_holdings", e)
        return pd.DataFrame()


# Backward-compatible re-exports from extracted brokerage.snaptrade package.
from brokerage.snaptrade._shared import (  # noqa: E402
    ApiException as _extracted_ApiException,
    _extract_snaptrade_body as _extracted_extract_snaptrade_body,
    _get_snaptrade_identity as _extracted_get_snaptrade_identity,
    _to_float as _extracted_to_float,
    handle_snaptrade_api_exception as _extracted_handle_snaptrade_api_exception,
    is_snaptrade_secret_error as _extracted_is_snaptrade_secret_error,
    with_snaptrade_retry as _extracted_with_snaptrade_retry,
)
from brokerage.snaptrade.client import (  # noqa: E402
    _cancel_order_with_retry as _extracted_cancel_order_with_retry,
    _delete_snap_trade_user_with_retry as _extracted_delete_snap_trade_user_with_retry,
    _detail_brokerage_authorization_with_retry as _extracted_detail_brokerage_authorization_with_retry,
    _get_order_impact_with_retry as _extracted_get_order_impact_with_retry,
    _get_user_account_balance_with_retry as _extracted_get_user_account_balance_with_retry,
    _get_user_account_orders_with_retry as _extracted_get_user_account_orders_with_retry,
    _get_user_account_positions_with_retry as _extracted_get_user_account_positions_with_retry,
    _list_user_accounts_with_retry as _extracted_list_user_accounts_with_retry,
    _login_snap_trade_user_with_retry as _extracted_login_snap_trade_user_with_retry,
    _place_order_with_retry as _extracted_place_order_with_retry,
    _reset_snap_trade_user_secret_with_retry as _extracted_reset_snap_trade_user_secret_with_retry,
    _register_snap_trade_user_with_retry as _extracted_register_snap_trade_user_with_retry,
    _remove_brokerage_authorization_with_retry as _extracted_remove_brokerage_authorization_with_retry,
    _symbol_search_user_account_with_retry as _extracted_symbol_search_user_account_with_retry,
    get_snaptrade_client as _extracted_get_snaptrade_client,
    snaptrade_client as _extracted_snaptrade_client,
)
from brokerage.snaptrade.recovery import (  # noqa: E402
    _get_rotation_lock as _extracted_get_rotation_lock,
    _try_rotate_secret as _extracted_try_rotate_secret,
    recover_snaptrade_auth as _extracted_recover_snaptrade_auth,
    rotate_snaptrade_user_secret as _extracted_rotate_snaptrade_user_secret,
)
from brokerage.snaptrade.connections import (  # noqa: E402
    check_snaptrade_connection_health as _extracted_check_snaptrade_connection_health,
    create_snaptrade_connection_url as _extracted_create_snaptrade_connection_url,
    list_snaptrade_connections as _extracted_list_snaptrade_connections,
    remove_snaptrade_connection as _extracted_remove_snaptrade_connection,
    upgrade_snaptrade_connection_to_trade as _extracted_upgrade_snaptrade_connection_to_trade,
)
from brokerage.snaptrade.secrets import (  # noqa: E402
    delete_snaptrade_user_secret as _extracted_delete_snaptrade_user_secret,
    get_snaptrade_app_credentials as _extracted_get_snaptrade_app_credentials,
    get_snaptrade_user_secret as _extracted_get_snaptrade_user_secret,
    store_snaptrade_app_credentials as _extracted_store_snaptrade_app_credentials,
    store_snaptrade_user_secret as _extracted_store_snaptrade_user_secret,
)
from brokerage.snaptrade.trading import (  # noqa: E402
    cancel_snaptrade_order as _extracted_cancel_snaptrade_order,
    get_snaptrade_orders as _extracted_get_snaptrade_orders,
    place_snaptrade_checked_order as _extracted_place_snaptrade_checked_order,
    preview_snaptrade_order as _extracted_preview_snaptrade_order,
    search_snaptrade_symbol as _extracted_search_snaptrade_symbol,
)
from brokerage.snaptrade.users import (  # noqa: E402
    delete_snaptrade_user as _extracted_delete_snaptrade_user,
    get_snaptrade_user_id_from_email as _extracted_get_snaptrade_user_id_from_email,
    register_snaptrade_user as _extracted_register_snaptrade_user,
)

get_snaptrade_client = _extracted_get_snaptrade_client
store_snaptrade_app_credentials = _extracted_store_snaptrade_app_credentials
get_snaptrade_app_credentials = _extracted_get_snaptrade_app_credentials
store_snaptrade_user_secret = _extracted_store_snaptrade_user_secret
get_snaptrade_user_secret = _extracted_get_snaptrade_user_secret
delete_snaptrade_user_secret = _extracted_delete_snaptrade_user_secret
get_snaptrade_user_id_from_email = _extracted_get_snaptrade_user_id_from_email
register_snaptrade_user = _extracted_register_snaptrade_user
delete_snaptrade_user = _extracted_delete_snaptrade_user
create_snaptrade_connection_url = _extracted_create_snaptrade_connection_url
upgrade_snaptrade_connection_to_trade = _extracted_upgrade_snaptrade_connection_to_trade
list_snaptrade_connections = _extracted_list_snaptrade_connections
check_snaptrade_connection_health = _extracted_check_snaptrade_connection_health
remove_snaptrade_connection = _extracted_remove_snaptrade_connection
handle_snaptrade_api_exception = _extracted_handle_snaptrade_api_exception
with_snaptrade_retry = _extracted_with_snaptrade_retry
is_snaptrade_secret_error = _extracted_is_snaptrade_secret_error
ApiException = _extracted_ApiException
_register_snap_trade_user_with_retry = _extracted_register_snap_trade_user_with_retry
_login_snap_trade_user_with_retry = _extracted_login_snap_trade_user_with_retry
_list_user_accounts_with_retry = _extracted_list_user_accounts_with_retry
_detail_brokerage_authorization_with_retry = _extracted_detail_brokerage_authorization_with_retry
_get_user_account_positions_with_retry = _extracted_get_user_account_positions_with_retry
_get_user_account_balance_with_retry = _extracted_get_user_account_balance_with_retry
_remove_brokerage_authorization_with_retry = _extracted_remove_brokerage_authorization_with_retry
_delete_snap_trade_user_with_retry = _extracted_delete_snap_trade_user_with_retry
_reset_snap_trade_user_secret_with_retry = _extracted_reset_snap_trade_user_secret_with_retry
_symbol_search_user_account_with_retry = _extracted_symbol_search_user_account_with_retry
_get_order_impact_with_retry = _extracted_get_order_impact_with_retry
_place_order_with_retry = _extracted_place_order_with_retry
_get_user_account_orders_with_retry = _extracted_get_user_account_orders_with_retry
_cancel_order_with_retry = _extracted_cancel_order_with_retry
_extract_snaptrade_body = _extracted_extract_snaptrade_body
_get_snaptrade_identity = _extracted_get_snaptrade_identity
_to_float = _extracted_to_float
_get_rotation_lock = _extracted_get_rotation_lock
_try_rotate_secret = _extracted_try_rotate_secret
rotate_snaptrade_user_secret = _extracted_rotate_snaptrade_user_secret
recover_snaptrade_auth = _extracted_recover_snaptrade_auth
search_snaptrade_symbol = _extracted_search_snaptrade_symbol
preview_snaptrade_order = _extracted_preview_snaptrade_order
place_snaptrade_checked_order = _extracted_place_snaptrade_checked_order
get_snaptrade_orders = _extracted_get_snaptrade_orders
cancel_snaptrade_order = _extracted_cancel_snaptrade_order

# Initialize default client on module import (if enabled)
snaptrade_client = _extracted_snaptrade_client
