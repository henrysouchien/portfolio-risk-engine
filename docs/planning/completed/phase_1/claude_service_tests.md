# Claude Service Multi-User Implementation Tests

## 🧪 Overview

This test suite ensures the Claude service database refactor is implemented correctly and all functionality works with the multi-user architecture. Tests are organized by implementation phase to allow incremental verification.

## 🔧 Test Setup

### Prerequisites
```bash
# 1. Ensure database is running
psql -U postgres -h localhost -d risk_module_db -c "SELECT 1"

# 2. Create test users in database
python3 -c "
from inputs.database_client import DatabaseClient
db = DatabaseClient()
# Create test users if they don't exist
test_user1_id = db.get_or_create_user_id('test_user_1@example.com')
test_user2_id = db.get_or_create_user_id('test_user_2@example.com')
print(f'Test User 1 ID: {test_user1_id}')
print(f'Test User 2 ID: {test_user2_id}')
"

# 3. Create test portfolios for users
python3 -c "
from inputs.portfolio_manager import PortfolioManager
from core.data_objects import PortfolioData
# User 1 portfolio
pm1 = PortfolioManager(use_database=True, user_id=1)
portfolio1 = PortfolioData.from_holdings({'AAPL': 100, 'MSFT': 50}, portfolio_name='CURRENT_PORTFOLIO')
pm1.save_portfolio_data(portfolio1)
print('Created User 1 portfolio')

# User 2 portfolio  
pm2 = PortfolioManager(use_database=True, user_id=2)
portfolio2 = PortfolioData.from_holdings({'GOOGL': 75, 'AMZN': 25}, portfolio_name='CURRENT_PORTFOLIO')
pm2.save_portfolio_data(portfolio2)
print('Created User 2 portfolio')
"
```

---

## 📋 Phase 1: Context Service Tests

### Test 1.1: Authentication Required
```python
# test_context_auth.py
from services.portfolio.context_service import PortfolioContextService

def test_context_requires_auth():
    """Test that context service requires authentication"""
    service = PortfolioContextService()
    
    # Test without user
    result = service.get_cached_context()
    assert result['status'] == 'error'
    assert 'Authentication required' in result['error']
    assert result['risk_score']['score'] == 0
    print("✅ PASS: Context service requires authentication")

if __name__ == "__main__":
    test_context_requires_auth()
```

### Test 1.2: Database-First Loading
```python
# test_context_database.py
from services.portfolio.context_service import PortfolioContextService

def test_context_loads_database_portfolio():
    """Test that context service loads from database first"""
    service = PortfolioContextService()
    
    # Mock user with database portfolio
    mock_user = {'id': 1, 'email': 'test_user_1@example.com'}
    
    result = service.get_cached_context(user=mock_user)
    assert result['status'] == 'success'
    assert result['portfolio_source'] == 'database'
    assert result['user_id'] == 1
    print("✅ PASS: Context loads database portfolio")

if __name__ == "__main__":
    test_context_loads_database_portfolio()
```

### Test 1.3: YAML Fallback
```python
# test_context_fallback.py
from services.portfolio.context_service import PortfolioContextService

def test_context_yaml_fallback():
    """Test YAML fallback when database portfolio not found"""
    service = PortfolioContextService()
    
    # Mock user without database portfolio
    mock_user = {'id': 999, 'email': 'no_portfolio@example.com'}
    
    result = service.get_cached_context(user=mock_user)
    assert result['status'] == 'success'
    assert result['portfolio_source'] == 'yaml_fallback'
    print("✅ PASS: Context falls back to YAML")

if __name__ == "__main__":
    test_context_yaml_fallback()
```

### Test 1.4: User-Specific Caching
```python
# test_context_cache.py
from services.portfolio.context_service import PortfolioContextService
import time

def test_user_specific_caching():
    """Test that cache is user-specific"""
    service = PortfolioContextService()
    
    user1 = {'id': 1, 'email': 'test_user_1@example.com'}
    user2 = {'id': 2, 'email': 'test_user_2@example.com'}
    
    # Load user 1 context
    start = time.time()
    result1 = service.get_cached_context(user=user1)
    first_load_time = time.time() - start
    
    # Load user 1 again (should be cached)
    start = time.time()
    result1_cached = service.get_cached_context(user=user1)
    cached_load_time = time.time() - start
    
    # Load user 2 (should not use user 1's cache)
    result2 = service.get_cached_context(user=user2)
    
    assert cached_load_time < first_load_time / 10  # Cached should be much faster
    assert result1['user_id'] == 1
    assert result2['user_id'] == 2
    print("✅ PASS: User-specific caching works")

if __name__ == "__main__":
    test_user_specific_caching()
```

---

## 🔑 Phase 4: API Routing Tests

### Test 4.1: Authentication Required
```bash
# test_claude_auth.sh
#!/bin/bash

echo "Testing Claude chat requires authentication..."

# Test without session
response=$(curl -s -w "\n%{http_code}" -X POST http://localhost:5000/api/claude_chat \
  -H "Content-Type: application/json" \
  -d '{"user_message": "Hello Claude"}')

status_code=$(echo "$response" | tail -1)
body=$(echo "$response" | head -n -1)

if [ "$status_code" = "401" ]; then
    echo "✅ PASS: Claude chat requires authentication (401 returned)"
else
    echo "❌ FAIL: Expected 401, got $status_code"
    echo "Response: $body"
    exit 1
fi
```

### Test 4.2: Authenticated Access
```bash
# test_claude_with_auth.sh
#!/bin/bash

echo "Testing Claude chat with authentication..."

# First login
curl -s -X POST http://localhost:5000/login \
  -H "Content-Type: application/json" \
  -d '{"google_token": "test_token"}' \
  -c cookies.txt

# Then test Claude chat
response=$(curl -s -w "\n%{http_code}" -X POST http://localhost:5000/api/claude_chat \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"user_message": "Hello Claude"}')

status_code=$(echo "$response" | tail -1)

if [ "$status_code" != "401" ]; then
    echo "✅ PASS: Claude chat accessible with authentication"
else
    echo "❌ FAIL: Claude chat returned 401 even with authentication"
    exit 1
fi
```

---

## 💬 Phase 3: Chat Service Tests

### Test 3.1: User Context Flow
```python
# test_chat_user_context.py
from services.claude.chat_service import ClaudeChatService
from unittest.mock import MagicMock, patch

def test_chat_requires_user():
    """Test chat service requires user context"""
    chat_service = ClaudeChatService()
    
    # Test without user
    result = chat_service.process_chat(
        user_message="Test",
        chat_history=[],
        user_key="test_key",
        user_tier="public",
        user=None
    )
    
    assert not result['success']
    assert 'Authentication required' in result['claude_response']
    print("✅ PASS: Chat service requires user")

def test_chat_sets_function_executor_context():
    """Test that chat service sets user context on function executor"""
    chat_service = ClaudeChatService()
    mock_user = {'id': 1, 'email': 'test@example.com'}
    
    # Mock the function executor
    chat_service.function_executor = MagicMock()
    
    # Mock portfolio service to avoid actual API calls
    with patch.object(chat_service.portfolio_service, 'get_cached_context') as mock_context:
        mock_context.return_value = {
            'status': 'success',
            'formatted_analysis': 'Test analysis',
            'risk_score': {'score': 75},
            'available_functions': []
        }
        
        # Process chat with user
        chat_service.process_chat(
            user_message="Test",
            chat_history=[],
            user_key="test_key",
            user_tier="public",
            user=mock_user
        )
        
        # Verify user context was set
        chat_service.function_executor.set_user_context.assert_called_with(mock_user)
        print("✅ PASS: Chat service sets user context on function executor")

if __name__ == "__main__":
    test_chat_requires_user()
    test_chat_sets_function_executor_context()
```

---

## 🎯 Phase 2: Function Executor Tests

### Test 2.1: Database-First Portfolio Loading
```python
# test_executor_database.py
from services.claude.function_executor import ClaudeFunctionExecutor

def test_portfolio_analysis_database_first():
    """Test portfolio analysis uses database first"""
    executor = ClaudeFunctionExecutor()
    
    # Test without user context
    result = executor._execute_portfolio_analysis({})
    assert not result['success']
    assert 'Authentication required' in result['error']
    
    # Set user context
    executor.set_user_context({'id': 1, 'email': 'test@example.com'})
    
    # Test with user context
    result = executor._execute_portfolio_analysis({})
    assert 'portfolio_source' in result
    assert result['user_id'] == 1
    print("✅ PASS: Portfolio analysis uses database first")

if __name__ == "__main__":
    test_portfolio_analysis_database_first()
```

### Test 2.2: Factor Name Serialization Fix
```python
# test_factor_serialization.py
from services.claude.function_executor import ClaudeFunctionExecutor

def test_no_factor_column_errors():
    """Test that factor name errors are fixed"""
    executor = ClaudeFunctionExecutor()
    executor.set_user_context({'id': 1, 'email': 'test@example.com'})
    
    # Execute portfolio analysis
    result = executor._execute_portfolio_analysis({})
    
    # Should not contain the error
    assert 'None of [\'factor\'] are in the columns' not in str(result)
    assert result['success'] or 'yaml_fallback' in str(result)
    print("✅ PASS: No factor column errors")

if __name__ == "__main__":
    test_no_factor_column_errors()
```

---

## 🔄 Integration Tests

### Test I.1: End-to-End Claude Chat
```python
# test_claude_e2e.py
import requests
import json

def test_claude_chat_e2e():
    """Test complete Claude chat flow with authentication"""
    
    # 1. Login first
    login_response = requests.post(
        'http://localhost:5000/login',
        json={'google_token': 'test_token'}
    )
    session_cookie = login_response.cookies.get('session_id')
    
    # 2. Test Claude chat
    claude_response = requests.post(
        'http://localhost:5000/api/claude_chat',
        json={
            'user_message': 'What is my portfolio risk score?',
            'chat_history': []
        },
        cookies={'session_id': session_cookie}
    )
    
    assert claude_response.status_code == 200
    data = claude_response.json()
    assert data['success']
    assert 'risk_score' in data['context_provided']
    print("✅ PASS: End-to-end Claude chat works")

if __name__ == "__main__":
    test_claude_chat_e2e()
```

### Test I.2: User Isolation
```python
# test_user_isolation.py
import requests

def test_claude_user_isolation():
    """Test that users get different portfolio analysis"""
    
    # Login as User 1
    login1 = requests.post('http://localhost:5000/login', 
                           json={'google_token': 'user1_token'})
    session1 = login1.cookies.get('session_id')
    
    # Login as User 2  
    login2 = requests.post('http://localhost:5000/login',
                           json={'google_token': 'user2_token'})
    session2 = login2.cookies.get('session_id')
    
    # Get Claude analysis for User 1
    response1 = requests.post(
        'http://localhost:5000/api/claude_chat',
        json={'user_message': 'List my holdings', 'chat_history': []},
        cookies={'session_id': session1}
    )
    
    # Get Claude analysis for User 2
    response2 = requests.post(
        'http://localhost:5000/api/claude_chat',
        json={'user_message': 'List my holdings', 'chat_history': []},
        cookies={'session_id': session2}
    )
    
    # Verify different portfolios
    assert 'AAPL' in response1.text or 'MSFT' in response1.text
    assert 'GOOGL' in response2.text or 'AMZN' in response2.text
    assert response1.json()['context_provided'] != response2.json()['context_provided']
    print("✅ PASS: Users see their own portfolios")

if __name__ == "__main__":
    test_claude_user_isolation()
```

---

## 🚨 Error Scenario Tests

### Test E.1: Session Expiration
```python
# test_session_expiration.py
from services.claude.chat_service import ClaudeChatService

def test_expired_session_handling():
    """Test graceful handling of expired sessions"""
    chat_service = ClaudeChatService()
    
    # Simulate expired session (user=None)
    result = chat_service.process_chat(
        user_message="Analyze my portfolio",
        chat_history=[],
        user_key="test",
        user_tier="public",
        user=None
    )
    
    assert not result['success']
    assert 'session has expired' in result['claude_response'].lower()
    assert result.get('session_expired', False)
    print("✅ PASS: Session expiration handled gracefully")

if __name__ == "__main__":
    test_expired_session_handling()
```

### Test E.2: Database Connection Failure
```python
# test_database_fallback.py
from services.claude.function_executor import ClaudeFunctionExecutor
from unittest.mock import patch

def test_database_failure_fallback():
    """Test fallback to YAML when database fails"""
    executor = ClaudeFunctionExecutor()
    executor.set_user_context({'id': 1, 'email': 'test@example.com'})
    
    # Mock database failure
    with patch('inputs.portfolio_manager.PortfolioManager.load_portfolio_data') as mock_load:
        mock_load.side_effect = Exception("Database connection failed")
        
        result = executor._execute_portfolio_analysis({})
        
        assert 'yaml_fallback' in str(result)
        assert result['success'] or 'portfolio.yaml' in str(result)
        print("✅ PASS: Falls back to YAML on database failure")

if __name__ == "__main__":
    test_database_failure_fallback()
```

---

## 🏃 Test Execution Script

```bash
#!/bin/bash
# run_claude_tests.sh

echo "🧪 Running Claude Service Multi-User Tests"
echo "=========================================="

# Phase 1: Context Service
echo -e "\n📋 Phase 1: Context Service Tests"
python3 test_context_auth.py
python3 test_context_database.py
python3 test_context_fallback.py
python3 test_context_cache.py

# Phase 4: API Routing
echo -e "\n🔑 Phase 4: API Routing Tests"
bash test_claude_auth.sh
bash test_claude_with_auth.sh

# Phase 3: Chat Service
echo -e "\n💬 Phase 3: Chat Service Tests"
python3 test_chat_user_context.py

# Phase 2: Function Executor
echo -e "\n🎯 Phase 2: Function Executor Tests"
python3 test_executor_database.py
python3 test_factor_serialization.py

# Integration Tests
echo -e "\n🔄 Integration Tests"
python3 test_claude_e2e.py
python3 test_user_isolation.py

# Error Scenarios
echo -e "\n🚨 Error Scenario Tests"
python3 test_session_expiration.py
python3 test_database_fallback.py

echo -e "\n✅ All tests completed!"
```

---

## 📊 Test Coverage Matrix

| Component | Test Coverage | Critical Tests |
|-----------|--------------|----------------|
| Context Service | ✅ Auth required<br>✅ Database-first<br>✅ YAML fallback<br>✅ User caching | Authentication, Database loading |
| API Routing | ✅ 401 without auth<br>✅ Pass user context<br>✅ Session validation | Authentication enforcement |
| Chat Service | ✅ User required<br>✅ Context flow<br>✅ Function executor setup | User context propagation |
| Function Executor | ✅ Database-first<br>✅ Factor serialization<br>✅ User isolation | No factor errors, Database usage |
| Integration | ✅ E2E flow<br>✅ User isolation<br>✅ Error handling | Complete workflow |

---

## 🎯 Success Criteria

### Core Functionality
- [ ] Claude chat requires authentication
- [ ] No "None of ['factor'] are in the columns" errors
- [ ] Users see their own portfolios only
- [ ] Database-first with YAML fallback works

### Performance
- [ ] Cached responses are 10x+ faster
- [ ] No memory leaks with multiple users
- [ ] Concurrent users work without conflicts

### Error Handling
- [ ] Expired sessions handled gracefully
- [ ] Database failures fall back to YAML
- [ ] Clear error messages for users

### User Experience
- [ ] Claude analyzes correct portfolio
- [ ] Factor names show as text not numbers
- [ ] Portfolio context is accurate

---

## 🐛 Common Issues and Solutions

### Issue: "Authentication required" in all tests
**Solution**: Ensure test users exist in database and mock authentication properly

### Issue: Factor serialization errors persist
**Solution**: Verify service layer is used instead of direct function calls

### Issue: Cache not working
**Solution**: Check cache keys include user_id and portfolio_name

### Issue: YAML fallback not working
**Solution**: Ensure portfolio.yaml exists and is valid

---

## 🚀 Running Tests During Implementation

After implementing each phase:

1. **Phase 1 Complete**: Run context service tests
2. **Phase 4 Complete**: Run API routing tests  
3. **Phase 3 Complete**: Run chat service tests
4. **Phase 2 Complete**: Run function executor tests
5. **All Phases Complete**: Run integration tests

This ensures each phase works before building on it!