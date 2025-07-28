# Security Implementation Plan - Pre-Deployment Checklist

## Overview
This document outlines critical security improvements needed before production deployment. Current architecture has solid foundations but lacks several standard web security layers.

## Current Security Status ✅
- ✅ Session-based authentication with Google OAuth
- ✅ Rate limiting per user tier (public/registered/paid)
- ✅ Database parameterized queries (SQL injection protection)
- ✅ User data isolation via user_id scoping
- ✅ Environment variable separation (secrets not in frontend)
- ✅ CORS configured for development

## Critical Security Gaps to Address

### 🔴 HIGH PRIORITY (Must Fix Before Production)

#### 1. CSRF Protection
**Issue**: State-changing operations vulnerable to Cross-Site Request Forgery
**Risk**: Malicious sites could perform actions on behalf of authenticated users

**Implementation:**
```python
# Add to requirements.txt
flask-wtf>=1.1.1

# In app.py
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)

# Frontend: Include CSRF token in headers
headers['X-CSRFToken'] = await getCsrfToken();
```

**Affected Endpoints:**
- `POST /api/portfolios` (create portfolio)
- `PUT /api/portfolios/<name>` (update portfolio)
- `DELETE /api/portfolios/<name>` (delete portfolio)
- `POST /api/risk-settings` (update risk settings)

#### 2. Security Headers Middleware
**Issue**: Missing standard security headers
**Risk**: XSS, clickjacking, MIME-sniffing attacks

**Implementation:**
```python
# Create utils/security_headers.py
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    return response
```

### 🟡 MEDIUM PRIORITY (Should Fix Before Production)

#### 3. Input Validation & Sanitization
**Issue**: Weak input validation using basic `.get()` methods
**Risk**: Data corruption, injection attacks via malformed inputs

**Implementation:**
```python
# Add to requirements.txt
marshmallow>=3.19.0

# Create schemas/portfolio_schemas.py
from marshmallow import Schema, fields, validate

class CreatePortfolioSchema(Schema):
    portfolio_name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    holdings = fields.Dict(required=True, validate=validate.Length(min=1))
    start_date = fields.Date(allow_none=True)
    end_date = fields.Date(allow_none=True)

# In routes, replace:
data = request.json or {}
portfolio_name = data.get('portfolio_name')

# With:
schema = CreatePortfolioSchema()
try:
    validated_data = schema.load(request.json)
except ValidationError as e:
    return jsonify_error_response(message="Invalid input", details=e.messages)
```

#### 4. Enhanced Session Security
**Issue**: Basic session configuration
**Risk**: Session hijacking, insufficient session management

**Implementation:**
```python
# In app.py
app.config.update(
    SESSION_COOKIE_SECURE=True,  # HTTPS only
    SESSION_COOKIE_HTTPONLY=True,  # No JS access
    SESSION_COOKIE_SAMESITE='Lax',  # CSRF protection
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24)  # Auto logout
)

# Add session validation
def validate_session_security():
    # Check session age, IP consistency, etc.
    pass
```

#### 5. Error Information Disclosure Prevention
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
- [ ] CSRF token validation works
- [ ] Security headers present in responses
- [ ] Input validation rejects malformed data
- [ ] Error messages don't leak sensitive info
- [ ] CORS properly restricts origins
- [ ] Sessions expire appropriately
- [ ] Rate limiting functions correctly

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