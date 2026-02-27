# User ID Inconsistency Fix Summary

## The Problem

The system has inconsistent field naming for user IDs across different components:

1. **auth_service** returns:
   ```python
   {
       'user_id': 123,            # Integer database ID
       'google_user_id': 'sub123', # String from Google
       'email': 'user@example.com',
       'name': 'User Name',
       'tier': 'registered'
   }
   ```

2. **routes/api.py** transforms this to:
   ```python
   {
       'id': 123,                  # Renamed from 'user_id'!
       'google_user_id': 'sub123',
       'email': 'user@example.com',
       'name': 'User Name',
       'auth_provider': 'google'
   }
   ```

3. **Claude services** expect `user['user_id']` but might receive `user['id']`

## Additional Issues

1. **Plaid routes** use email as user identifier instead of database ID
2. **Portfolio context service** looks for both `user['user_id']` and `user['id']`
3. **Mixing of data types**: Some code expects integers, some strings

## Root Cause

The system evolved from email-based identification to database IDs, and different components were updated at different times with different conventions.

## Recommended Fixes

### Option 1: Standardize on 'user_id' (Minimal Changes)
1. Keep auth_service as-is (returns `user_id`)
2. Remove the transformation in routes/api.py
3. Ensure all services consistently use `user['user_id']`

### Option 2: Standardize on 'id' (More Aligned with REST conventions)
1. Update auth_service to return `id` instead of `user_id`
2. Update all services to use `user['id']`
3. Keep routes/api.py transformation

### Option 3: Support Both (Backwards Compatible)
1. Make auth_service return both `id` and `user_id` with same value
2. Update services to check for both fields
3. Gradually migrate to single field

## Quick Fix for Current Error

The immediate fix for the "user_id is None" error is to ensure consistent field naming. Since Claude routes call auth_service directly (not through api.py transformation), they get `user_id` field, which works correctly.

The issue likely occurs when Claude is called through a different flow that uses the api.py transformation.

## Implementation Priority

1. **Immediate**: Fix Plaid routes to use database user_id instead of email
2. **Short-term**: Standardize field naming across all services  
3. **Long-term**: Add validation to ensure user objects have required fields