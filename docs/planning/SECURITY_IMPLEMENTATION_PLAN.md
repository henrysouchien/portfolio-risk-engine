# Security Implementation Plan - Pre-Deployment Checklist

## Overview
This document outlines remaining security improvements needed before production deployment. Current FastAPI architecture has excellent modern security foundations with comprehensive built-in protections.

## Current Security Status ✅ (FastAPI Architecture)
- ✅ **FastAPI Framework** with automatic Pydantic validation and OpenAPI docs
- ✅ **Session-based authentication** with Google OAuth and database-backed sessions
- ✅ **Rate limiting** per user tier (public/registered/paid) via SlowAPI middleware
- ✅ **Input validation** via comprehensive Pydantic models (15+ response models)
- ✅ **Database parameterized queries** (SQL injection protection)
- ✅ **User data isolation** via user_id scoping and dependency injection
- ✅ **Environment variable separation** (secrets not in frontend)
- ✅ **CORS middleware** properly configured for React frontend
- ✅ **Session middleware** with HTTP-only cookies and secure configuration
- ✅ **Comprehensive logging** and audit trails for all user actions

## Critical Security Gaps to Address

### 🔴 HIGH PRIORITY (Must Fix Before Production)

#### 1. CSRF Protection (FastAPI)
**Issue**: State-changing operations vulnerable to Cross-Site Request Forgery
**Risk**: Malicious sites could perform actions on behalf of authenticated users

**Implementation:**
```python
# Add to requirements.txt
fastapi-csrf-protect>=0.3.0

# In app.py
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError

# Configure CSRF protection
@CsrfProtect.load_config
def get_csrf_config():
    return {
        'secret_key': os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production"),
        'cookie_samesite': 'lax',
        'cookie_secure': os.getenv('ENVIRONMENT') == 'production'
    }

# Add CSRF dependency to state-changing endpoints
from fastapi import Depends
csrf_protect = CsrfProtect()

# Frontend: Include CSRF token in headers
headers['X-CSRF-Token'] = await getCsrfToken();
```

**Affected Endpoints:**
- `POST /api/portfolios` (create portfolio)
- `PUT /api/portfolios/<name>` (update portfolio)  
- `DELETE /api/portfolios/<name>` (delete portfolio)
- `POST /api/risk-settings` (update risk settings)
- `POST /auth/logout` (logout user)

#### 2. Security Headers Middleware (FastAPI)
**Issue**: Missing standard security headers
**Risk**: XSS, clickjacking, MIME-sniffing attacks

**Implementation:**
```python
# Create utils/security_headers.py
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # HSTS for production
        if os.getenv('ENVIRONMENT') == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        # CSP for React app
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.anthropic.com https://production.plaid.com;"
        )
        
        return response

# In app.py create_app() function
app.add_middleware(SecurityHeadersMiddleware)
```

### 🟡 MEDIUM PRIORITY (Should Fix Before Production)

#### 3. Python Dependencies Security Updates
**Issue**: Potentially outdated security-sensitive Python packages
**Risk**: Known vulnerabilities in cryptography, authentication, and web framework dependencies

**Implementation:**
```bash
# Check current versions and security vulnerabilities
pip list --outdated
pip-audit  # Install with: pip install pip-audit

# Priority packages to verify and update:
pip install --upgrade cryptography>=41.0.0  # Critical security updates
pip install --upgrade anthropic>=0.60.0     # AI service security patches  
pip install --upgrade flask>=2.3.0          # Web framework security fixes
pip install --upgrade requests>=2.31.0      # HTTP client security updates
pip install --upgrade google-auth>=2.22.0   # OAuth security improvements

# Verify no breaking changes in staging before production
python -m pytest tests/ --verbose
```

**Verification Steps:**
1. Run `pip-audit` to identify known vulnerabilities
2. Update packages in staging environment first
3. Run full test suite to ensure compatibility
4. Monitor application logs for any issues
5. Update requirements.txt with pinned secure versions

#### 4. Debug Code Cleanup
**Issue**: Production debug statements and development code remnants
**Risk**: Information disclosure, performance impact, potential security leaks

**Implementation:**
```bash
# Find debug statements across codebase
grep -r "print(" --include="*.py" . | grep -v "__pycache__" | grep -v ".git"
grep -r "DEBUG" --include="*.py" . | grep -v "__pycache__" | grep -v ".git"
grep -r "console.log" --include="*.js" --include="*.ts" --include="*.tsx" frontend/src/

# Remove or replace debug statements:
# Replace print() with proper logging
# Remove console.log() statements  
# Replace DEBUG=True with environment-based configuration
# Remove development-only code paths
```

**Cleanup Checklist:**
- [ ] Remove all `print()` statements (replace with `logger.debug()`)
- [ ] Remove all `console.log()` statements from frontend
- [ ] Replace hardcoded `DEBUG=True` with `os.getenv('DEBUG', 'false').lower() == 'true'`
- [ ] Remove development-only code blocks and comments
- [ ] Verify no sensitive data in debug output
- [ ] Test that logging levels work correctly in production

#### 5. Enhanced Session Security (Already Implemented ✅)
**Status**: ✅ **ALREADY IMPLEMENTED** in FastAPI architecture

**Current Implementation:**
```python
# ✅ CONFIRMED: Secure session middleware already configured (app.py:875-879)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
)

# ✅ CONFIRMED: HTTP-only cookies and secure session handling in AuthService
# ✅ CONFIRMED: Database-backed session management with automatic cleanup
# ✅ CONFIRMED: Proper session expiration and validation
```

**No Action Required** - Session security is properly implemented with FastAPI SessionMiddleware.

#### 6. Production OpenAPI Documentation Security
**Issue**: Interactive API documentation exposed in production
**Risk**: Information disclosure about API structure and endpoints

**Implementation:**
```python
# In app.py create_app() function
def create_app():
    # Disable docs in production
    docs_url = None if os.getenv('ENVIRONMENT') == 'production' else "/docs"
    redoc_url = None if os.getenv('ENVIRONMENT') == 'production' else "/redoc"
    
    app = FastAPI(
        title="Risk Module API", 
        version="2.0",
        description="Portfolio risk analysis and optimization API",
        docs_url=docs_url,
        redoc_url=redoc_url
    )
```

#### 7. Error Information Disclosure Prevention
**Issue**: Error messages may leak internal information
**Risk**: Information disclosure about system internals

**Implementation:**
```python
# In utils/errors.py - update error handling
def sanitize_error_message(error, is_production=True):
    if is_production:
        # Generic messages for production
        return "An error occurred. Please try again."
    else:
        # Detailed messages for development
        return str(error)

# Update error responses
return jsonify_error_response(
    message=sanitize_error_message(e, is_production()),
    # Remove: details={'error_type': type(e).__name__}
)
```

#### 6. Production CORS Configuration
**Issue**: CORS too permissive for production
**Risk**: Unauthorized cross-origin requests

**Implementation:**
```python
# In app.py - environment-specific CORS
if os.getenv('ENVIRONMENT') == 'production':
    CORS(app, origins=["https://yourdomain.com"], supports_credentials=True)
else:
    CORS(app, origins=["http://localhost:3000"], supports_credentials=True)
```

### 🟢 LOW PRIORITY (Nice to Have)

#### 7. Rate Limiting Enhancement
**Current**: Basic rate limiting per API key
**Enhancement**: More granular rate limiting

```python
# Add per-endpoint rate limiting
@limiter.limit("10 per minute", per_method=True)
@limiter.limit("100 per hour", per_method=True)
```

#### 8. Audit Logging
**Enhancement**: Security event logging

```python
# Log security events
def log_security_event(event_type, user_id, details):
    security_logger.warning(f"SECURITY_EVENT: {event_type}", extra={
        'user_id': user_id,
        'event': event_type,
        'details': details,
        'timestamp': datetime.now(UTC).isoformat(),
        'ip': request.remote_addr
    })
```

#### 9. API Versioning
**Enhancement**: API version management for security updates

```python
# Add version headers
@app.before_request
def check_api_version():
    version = request.headers.get('API-Version', 'v1')
    if version not in ['v1']:
        return jsonify({'error': 'Unsupported API version'}), 400
```

## Implementation Timeline

### Phase 1: Critical Security (Before Any Production Deploy)
- [ ] CSRF Protection implementation
- [ ] Security headers middleware
- [ ] Production CORS configuration
- [ ] Error message sanitization

### Phase 2: Enhanced Security (Within 2 weeks of production)
- [ ] Input validation schemas
- [ ] Enhanced session security
- [ ] Audit logging for security events

### Phase 3: Security Hardening (Ongoing)
- [ ] Enhanced rate limiting
- [ ] API versioning
- [ ] Security monitoring and alerting

## Testing Requirements

### Security Testing Checklist
- [ ] **FastAPI CSRF protection** works with fastapi-csrf-protect
- [ ] **Security headers middleware** present in all responses
- [ ] **Pydantic input validation** rejects malformed data (✅ already implemented)
- [ ] **Error messages** don't leak sensitive info
- [ ] **CORS middleware** properly restricts origins (✅ already implemented)
- [ ] **Sessions expire** appropriately (✅ already implemented)
- [ ] **Rate limiting** functions correctly via SlowAPI (✅ already implemented)
- [ ] **Python dependencies** have no known vulnerabilities (`pip-audit` passes)
- [ ] **No debug statements** in production code
- [ ] **Logging levels** configured correctly for production
- [ ] **FastAPI OpenAPI docs** disabled in production (`docs_url=None`)
- [ ] **Database session isolation** working correctly (✅ already implemented)

### Penetration Testing
- [ ] OWASP ZAP scan
- [ ] Manual CSRF testing
- [ ] Input fuzzing
- [ ] Session management testing

## Deployment Security Checklist

### Environment Configuration
- [ ] `ENVIRONMENT=production` set
- [ ] Strong `FLASK_SECRET_KEY` (32+ random chars)
- [ ] Database connection over SSL
- [ ] All secrets in environment variables (not code)
- [ ] HTTPS certificate configured
- [ ] Security headers configured in web server
- [ ] Python dependencies updated to secure versions
- [ ] All debug code removed from production build
- [ ] Production logging levels configured (no DEBUG output)

### Monitoring Setup
- [ ] Security event logging configured
- [ ] Failed login attempt monitoring
- [ ] Rate limit violation alerting
- [ ] Error rate monitoring
- [ ] Database connection monitoring

## Emergency Response Plan

### Security Incident Response
1. **Immediate**: Disable affected endpoints
2. **Within 1 hour**: Assess impact and containment
3. **Within 4 hours**: Deploy hotfix if needed
4. **Within 24 hours**: Full incident analysis
5. **Within 48 hours**: Security review and improvements

### Contact Information
- Security Lead: [Your Email]
- Infrastructure Team: [Team Contact]
- Emergency Escalation: [Manager Contact]

---

**Note**: This plan should be reviewed and updated quarterly. All security implementations should be tested in staging environment before production deployment.

**Last Updated**: January 26, 2025
**Next Review**: April 26, 2025