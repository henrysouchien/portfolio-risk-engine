# User ID Flow Analysis: Google OAuth to Database Access

## Overview
The system has a complex flow of user identification that involves mixing Google OAuth IDs (strings) with database user IDs (integers). This analysis traces the complete flow.

## 1. What Google Provides
- **Field**: `sub` (subject identifier)
- **Type**: String (e.g., "107123456789012345678")
- **Location**: In the ID token from Google OAuth
- **Extracted in**: `auth_service.verify_google_token()` line 112

```python
user_info = {
    'user_id': id_info['sub'],  # Google's 'sub' field (string)
    'email': id_info['email'],
    'name': id_info.get('name', ''),
    'google_user_id': id_info['sub']  # Same value stored twice
}
```

## 2. How auth_service Handles This

### In `create_user_session()` (line 173):
1. Receives `user_info` with Google's `sub` as both `user_id` and `google_user_id`
2. For database mode:
   - Calls `_create_or_update_user_database(user_info)` 
   - This calls `db_client.get_or_create_user_id()` which returns an **integer** database ID
   - Creates session with this integer user_id

### In `get_user_by_session()` (line 233):
Returns a user object with:
```python
{
    'user_id': result['user_id'],        # Integer from database
    'google_user_id': result['google_user_id'],  # String from Google
    'email': result['email'],
    'name': result['name'],
    'tier': result['tier']
}
```

## 3. What Gets Stored in Database

### Users table:
- `id` (INTEGER): Primary key, auto-incrementing
- `google_user_id` (VARCHAR): Google's 'sub' field
- `email`, `name`, `tier`: User details

### User_sessions table:
- `user_id` (INTEGER): Foreign key to users.id
- `session_id`: Generated session token

## 4. User Object Transformation

### In routes/api.py `get_current_user()`:
```python
# Transforms the auth_service response
return {
    'id': user['user_id'],  # Database integer ID
    'email': user['email'],
    'google_user_id': user['google_user_id'],  # Google string ID
    'name': user.get('name', ''),
    'auth_provider': user.get('auth_provider', 'google')
}
```

**KEY ISSUE**: The field name changes from `user_id` to `id`!

### In routes/plaid.py `get_current_user()`:
Uses the auth_service directly, so gets:
- `user['user_id']` - Database integer ID
- `user['google_user_id']` - Google string ID

## 5. Flow to Claude and PortfolioManager

### Claude (routes/claude.py):
1. Calls `get_current_user()` from auth_service (line 59)
2. Passes entire user object to `claude_service.process_chat()` (line 90)
3. Claude service expects `user['id']` but auth_service returns `user['user_id']`

### PortfolioManager:
1. Initialized with `user_id` parameter (can be int or string)
2. In database mode:
   - If integer: Uses directly as database ID
   - If string: Assumes it's Google ID and calls `get_or_create_user_id()`
3. Uses this for all database operations

## 6. The Mixing Problem

### Where String/Integer Mixing Occurs:

1. **Plaid Integration** (line 588):
   ```python
   store_plaid_token(
       user_id=user['email'],  # Using email as ID!
       ...
   )
   ```

2. **Portfolio Loading** (line 722):
   ```python
   holdings_df = load_all_user_holdings(
       user_id=user['email'],  # Using email again!
       ...
   )
   ```

3. **PortfolioManager Creation** (line 736):
   ```python
   portfolio_manager = PortfolioManager(
       use_database=True,
       user_id=user['user_id']  # Correctly uses integer ID
   )
   ```

## 7. Critical Issues Found

### Issue 1: Inconsistent Field Names
- `auth_service` returns `user['user_id']`
- `routes/api.py` transforms it to `user['id']`
- Claude expects `user['id']` but receives `user['user_id']`

### Issue 2: Email Used as User ID
- Plaid functions use `user['email']` as the user identifier
- This is inconsistent with the database design using integer IDs

### Issue 3: Function Executor Error
The function executor is looking for `user['user_id']` but in some flows it might receive `user['id']`, causing the "user_id is None" error.

## 8. Root Cause
The system has evolved from using email/Google IDs to database integer IDs, but not all components have been updated consistently. This creates a mismatch where:
- Some components expect `user['id']` (routes/api.py convention)
- Others expect `user['user_id']` (auth_service convention)
- Legacy code still uses email as the identifier

## 9. Recommended Fix
1. Standardize on one field name across all services (`user_id` or `id`)
2. Update all Plaid integrations to use database user IDs instead of emails
3. Ensure consistent user object structure throughout the application