# Frontend Refactoring Testing Script

## Overview

This testing script provides automated validation for each phase of the frontend refactoring plan. It ensures that functionality remains intact throughout the transformation from monolithic App.js to chassis + components architecture.

## Pre-Refactoring Baseline Test

**Purpose**: Establish baseline functionality before any changes

```bash
# Save current state
cp frontend/src/App.js frontend/src/App.baseline.js
git add -A
git commit -m "Baseline: Save working App.js before refactoring"

# Run baseline tests
npm test -- --testPathPattern=baseline
```

### Baseline Test Suite

```javascript
// tests/baseline.test.js
describe('Baseline Functionality', () => {
  beforeEach(() => {
    // Reset to clean state
    cy.visit('/');
  });

  it('Google Sign-In Flow Works', () => {
    cy.get('[data-testid="google-signin-button"]').should('exist');
    // Test sign-in flow
  });

  it('Portfolio Upload Works', () => {
    // Sign in first
    cy.signIn();
    
    // Test file upload
    cy.get('[data-testid="portfolio-upload"]').should('exist');
    cy.fixture('sample-portfolio.csv').then(fileContent => {
      cy.get('input[type="file"]').attachFile({
        fileContent,
        fileName: 'portfolio.csv',
        mimeType: 'text/csv'
      });
    });
    
    // Verify upload success
    cy.get('[data-testid="portfolio-data"]').should('exist');
  });

  it('Risk Analysis Works', () => {
    cy.signIn();
    cy.uploadPortfolio();
    
    // Test risk analysis
    cy.get('[data-testid="analyze-button"]').click();
    cy.get('[data-testid="risk-score"]').should('exist');
  });

  it('Plaid Integration Works', () => {
    cy.signIn();
    
    // Test Plaid link
    cy.get('[data-testid="plaid-link-button"]').click();
    cy.get('[data-testid="plaid-modal"]').should('exist');
  });

  it('Chat Interface Works', () => {
    cy.signIn();
    
    // Test chat
    cy.get('[data-testid="chat-input"]').type('Hello, can you help me?');
    cy.get('[data-testid="chat-send"]').click();
    cy.get('[data-testid="chat-messages"]').should('contain', 'Hello, can you help me?');
  });
});
```

## Phase 1: Foundation Testing

**Purpose**: Validate folder structure and context setup

```bash
# Run Phase 1 tests
npm test -- --testPathPattern=phase1
```

### Phase 1 Test Suite

```javascript
// tests/phase1.test.js
describe('Phase 1: Foundation', () => {
  it('Folder Structure Created', () => {
    const fs = require('fs');
    
    // Check chassis folders
    expect(fs.existsSync('src/chassis/managers')).toBe(true);
    expect(fs.existsSync('src/chassis/hooks')).toBe(true);
    expect(fs.existsSync('src/chassis/context')).toBe(true);
    
    // Check component folders
    expect(fs.existsSync('src/components/auth')).toBe(true);
    expect(fs.existsSync('src/components/portfolio')).toBe(true);
    expect(fs.existsSync('src/components/plaid')).toBe(true);
    expect(fs.existsSync('src/components/chat')).toBe(true);
    expect(fs.existsSync('src/components/layouts')).toBe(true);
    expect(fs.existsSync('src/components/shared')).toBe(true);
  });

  it('AppContext Created and Working', () => {
    const { render } = require('@testing-library/react');
    const { AppProvider, useAppContext } = require('../src/chassis/context/AppContext');
    
    const TestComponent = () => {
      const context = useAppContext();
      return <div data-testid="context-test">{context ? 'Context Working' : 'Context Failed'}</div>;
    };

    const { getByTestId } = render(
      <AppProvider>
        <TestComponent />
      </AppProvider>
    );

    expect(getByTestId('context-test')).toHaveTextContent('Context Working');
  });

  it('App.js Backup Created', () => {
    const fs = require('fs');
    expect(fs.existsSync('src/App.original.js')).toBe(true);
  });
});
```

## Phase 2: Chassis Manager Testing

**Purpose**: Validate manager classes and business logic

```bash
# Run Phase 2 tests
npm test -- --testPathPattern=phase2
```

### Phase 2 Test Suite

```javascript
// tests/phase2.test.js
describe('Phase 2: Chassis Managers', () => {
  describe('AuthManager', () => {
    it('Handles Google Sign-In', async () => {
      const { AuthManager } = require('../src/chassis/managers/AuthManager');
      const authManager = new AuthManager();
      
      const mockCredential = { credential: 'mock-token' };
      const user = await authManager.handleGoogleSignIn(mockCredential);
      
      expect(user).toBeDefined();
      expect(user.email).toBeDefined();
    });

    it('Handles Sign-Out', async () => {
      const { AuthManager } = require('../src/chassis/managers/AuthManager');
      const authManager = new AuthManager();
      
      const result = await authManager.signOut();
      expect(result).toBe(true);
    });
  });

  describe('PortfolioManager', () => {
    it('Uploads Portfolio', async () => {
      const { PortfolioManager } = require('../src/chassis/managers/PortfolioManager');
      const portfolioManager = new PortfolioManager();
      
      const mockFile = new File(['mock,data'], 'portfolio.csv', { type: 'text/csv' });
      const result = await portfolioManager.uploadPortfolio(mockFile);
      
      expect(result).toBeDefined();
      expect(result.positions).toBeDefined();
    });

    it('Analyzes Risk', async () => {
      const { PortfolioManager } = require('../src/chassis/managers/PortfolioManager');
      const portfolioManager = new PortfolioManager();
      
      const mockPortfolio = { positions: [{ symbol: 'AAPL', shares: 100 }] };
      const analysis = await portfolioManager.analyzeRisk(mockPortfolio);
      
      expect(analysis).toBeDefined();
      expect(analysis.riskScore).toBeDefined();
    });
  });

  describe('PlaidManager', () => {
    it('Creates Link Token', async () => {
      const { PlaidManager } = require('../src/chassis/managers/PlaidManager');
      const plaidManager = new PlaidManager();
      
      const token = await plaidManager.createLinkToken();
      expect(token).toBeDefined();
    });
  });

  describe('ChatManager', () => {
    it('Sends Message', async () => {
      const { ChatManager } = require('../src/chassis/managers/ChatManager');
      const chatManager = new ChatManager();
      
      const response = await chatManager.sendMessage('Hello');
      expect(response).toBeDefined();
    });
  });
});
```

## Phase 3: Custom Hooks Testing

**Purpose**: Validate hook interfaces and state management

```bash
# Run Phase 3 tests
npm test -- --testPathPattern=phase3
```

### Phase 3 Test Suite

```javascript
// tests/phase3.test.js
describe('Phase 3: Custom Hooks', () => {
  describe('useAuth', () => {
    it('Provides Sign-In Function', () => {
      const { renderHook } = require('@testing-library/react-hooks');
      const { useAuth } = require('../src/chassis/hooks/useAuth');
      const { AppProvider } = require('../src/chassis/context/AppContext');
      
      const wrapper = ({ children }) => <AppProvider>{children}</AppProvider>;
      const { result } = renderHook(() => useAuth(), { wrapper });
      
      expect(result.current.signIn).toBeDefined();
      expect(result.current.signOut).toBeDefined();
      expect(result.current.isAuthenticated).toBeDefined();
    });
  });

  describe('usePortfolio', () => {
    it('Provides Portfolio Functions', () => {
      const { renderHook } = require('@testing-library/react-hooks');
      const { usePortfolio } = require('../src/chassis/hooks/usePortfolio');
      const { AppProvider } = require('../src/chassis/context/AppContext');
      
      const wrapper = ({ children }) => <AppProvider>{children}</AppProvider>;
      const { result } = renderHook(() => usePortfolio(), { wrapper });
      
      expect(result.current.uploadPortfolio).toBeDefined();
      expect(result.current.analyzeRisk).toBeDefined();
      expect(result.current.loading).toBeDefined();
    });
  });

  describe('useChat', () => {
    it('Handles Chat State', () => {
      const { renderHook } = require('@testing-library/react-hooks');
      const { useChat } = require('../src/chassis/hooks/useChat');
      
      const { result } = renderHook(() => useChat());
      
      expect(result.current.messages).toBeDefined();
      expect(result.current.sendMessage).toBeDefined();
      expect(result.current.isStreaming).toBeDefined();
    });
  });
});
```

## Phase 4: Component Extraction Testing

**Purpose**: Validate each component extraction

```bash
# Run Phase 4 tests
npm test -- --testPathPattern=phase4
```

### Phase 4 Test Suite

```javascript
// tests/phase4.test.js
describe('Phase 4: Component Extraction', () => {
  describe('Authentication Components', () => {
    it('GoogleSignInButton Renders', () => {
      const { render } = require('@testing-library/react');
      const { GoogleSignInButton } = require('../src/components/auth/GoogleSignInButton');
      
      const { getByTestId } = render(
        <GoogleSignInButton onSuccess={() => {}} onError={() => {}} />
      );
      
      expect(getByTestId('google-signin-button')).toBeInTheDocument();
    });

    it('LandingPage Renders', () => {
      const { render } = require('@testing-library/react');
      const { LandingPage } = require('../src/components/auth/LandingPage');
      
      const { getByTestId } = render(
        <LandingPage onSignIn={() => {}} />
      );
      
      expect(getByTestId('landing-page')).toBeInTheDocument();
    });
  });

  describe('Portfolio Components', () => {
    it('RiskScoreDisplay Renders', () => {
      const { render } = require('@testing-library/react');
      const { RiskScoreDisplay } = require('../src/components/portfolio/RiskScoreDisplay');
      
      const mockRiskScore = { value: 5, breakdown: {} };
      const { getByTestId } = render(
        <RiskScoreDisplay riskScore={mockRiskScore} loading={false} />
      );
      
      expect(getByTestId('risk-score-display')).toBeInTheDocument();
    });
  });

  describe('Chat Components', () => {
    it('RiskAnalysisChat Renders', () => {
      const { render } = require('@testing-library/react');
      const { RiskAnalysisChat } = require('../src/components/chat/RiskAnalysisChat');
      
      const { getByTestId } = render(
        <RiskAnalysisChat portfolio={{}} isAuthenticated={true} />
      );
      
      expect(getByTestId('chat-interface')).toBeInTheDocument();
    });
  });
});
```

## Integration Testing

**Purpose**: Validate end-to-end functionality after each phase

```bash
# Run integration tests
npm run test:integration
```

### Integration Test Suite

```javascript
// tests/integration.test.js
describe('Integration Tests', () => {
  it('Complete Auth Flow', () => {
    cy.visit('/');
    
    // Test sign-in
    cy.get('[data-testid="google-signin-button"]').click();
    cy.get('[data-testid="user-profile"]').should('exist');
    
    // Test sign-out
    cy.get('[data-testid="signout-button"]').click();
    cy.get('[data-testid="landing-page"]').should('exist');
  });

  it('Complete Portfolio Flow', () => {
    cy.signIn();
    
    // Upload portfolio
    cy.uploadPortfolio();
    cy.get('[data-testid="portfolio-data"]').should('exist');
    
    // Analyze risk
    cy.get('[data-testid="analyze-button"]').click();
    cy.get('[data-testid="risk-score"]').should('exist');
  });

  it('Complete Chat Flow', () => {
    cy.signIn();
    cy.uploadPortfolio();
    
    // Send chat message
    cy.get('[data-testid="chat-input"]').type('Analyze my portfolio');
    cy.get('[data-testid="chat-send"]').click();
    
    // Verify response
    cy.get('[data-testid="chat-messages"]').should('contain', 'Analyze my portfolio');
    cy.get('[data-testid="chat-messages"] .ai-response').should('exist');
  });
});
```

## Rollback Scripts

**Purpose**: Quickly revert if tests fail

```bash
# Phase rollback script
./scripts/rollback.sh phase2
```

### Rollback Script

```bash
#!/bin/bash
# scripts/rollback.sh

PHASE=$1

case $PHASE in
  phase1)
    echo "Rolling back Phase 1..."
    rm -rf src/chassis
    rm -rf src/components
    git checkout HEAD~1 -- src/App.js
    ;;
  phase2)
    echo "Rolling back Phase 2..."
    rm -rf src/chassis/managers
    git checkout HEAD~1 -- src/chassis/
    ;;
  phase3)
    echo "Rolling back Phase 3..."
    rm -rf src/chassis/hooks
    git checkout HEAD~1 -- src/chassis/
    ;;
  phase4)
    echo "Rolling back Phase 4..."
    rm -rf src/components
    git checkout HEAD~1 -- src/
    ;;
  complete)
    echo "Rolling back to baseline..."
    cp src/App.original.js src/App.js
    rm -rf src/chassis
    rm -rf src/components
    ;;
  *)
    echo "Usage: $0 {phase1|phase2|phase3|phase4|complete}"
    exit 1
    ;;
esac

echo "Rollback complete. Running tests..."
npm test
```

## Test Execution Commands

```bash
# Run all tests
npm run test:refactoring

# Run specific phase
npm run test:phase1
npm run test:phase2
npm run test:phase3
npm run test:phase4

# Run integration tests
npm run test:integration

# Run with coverage
npm run test:coverage
```

### Package.json Test Scripts

```json
{
  "scripts": {
    "test:refactoring": "npm run test:baseline && npm run test:phase1 && npm run test:phase2 && npm run test:phase3 && npm run test:phase4 && npm run test:integration",
    "test:baseline": "jest --testPathPattern=baseline",
    "test:phase1": "jest --testPathPattern=phase1",
    "test:phase2": "jest --testPathPattern=phase2",
    "test:phase3": "jest --testPathPattern=phase3",
    "test:phase4": "jest --testPathPattern=phase4",
    "test:integration": "cypress run",
    "test:coverage": "jest --coverage"
  }
}
```

## Test Data Setup

### Sample Test Data

```javascript
// tests/fixtures/samplePortfolio.js
export const samplePortfolio = {
  positions: [
    { symbol: 'AAPL', shares: 100, price: 150.00 },
    { symbol: 'GOOGL', shares: 50, price: 2500.00 },
    { symbol: 'MSFT', shares: 75, price: 300.00 }
  ]
};

export const sampleRiskScore = {
  value: 6.5,
  breakdown: {
    concentration: 7,
    volatility: 6,
    correlation: 6
  }
};
```

## Continuous Testing

### GitHub Actions Workflow

```yaml
# .github/workflows/refactoring-tests.yml
name: Refactoring Tests

on:
  push:
    branches: [ refactoring ]
  pull_request:
    branches: [ refactoring ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Setup Node.js
      uses: actions/setup-node@v2
      with:
        node-version: '16'
        
    - name: Install dependencies
      run: npm ci
      
    - name: Run refactoring tests
      run: npm run test:refactoring
      
    - name: Upload coverage
      uses: codecov/codecov-action@v1
```

## Success Criteria

Each phase must pass:
- ✅ All existing functionality works
- ✅ No console errors
- ✅ All tests pass
- ✅ Code coverage maintained
- ✅ Performance not degraded

## Emergency Procedures

If major issues arise:
1. Run `./scripts/rollback.sh complete`
2. Verify baseline tests pass
3. Analyze what went wrong
4. Fix issues in isolated branch
5. Re-run from failed phase

This testing script ensures the refactoring is safe, validated, and can be quickly reverted if needed. 