# Pre-Refactoring Setup Guide

## Overview

Before starting the frontend refactoring, we need to add `data-testid` attributes to the existing App.js components so the baseline tests can validate current functionality. This ensures we have a reliable test foundation before any architectural changes.

## Step 1: Add Test IDs to Current App.js

### Authentication Components

```jsx
// Find Google Sign-In button in App.js and add:
<GoogleLogin
  data-testid="google-signin-button"
  onSuccess={handleCredentialResponse}
  onError={() => console.log('Login Failed')}
/>

// Find landing page container and add:
<div data-testid="landing-page" className="landing-page">
  <h1>Portfolio Risk Analysis</h1>
  {/* existing content */}
</div>

// Find sign-out button and add:
<button 
  data-testid="signout-button" 
  onClick={handleSignOut}
>
  Sign Out
</button>

// Find user profile display and add:
<div data-testid="user-profile">
  <img src={user.picture} alt="Profile" />
  <span>{user.name}</span>
</div>
```

### Portfolio Components

```jsx
// Find portfolio upload input and add:
<input
  data-testid="portfolio-upload"
  type="file"
  accept=".csv,.xlsx,.xls"
  onChange={handleFileUpload}
/>

// Find portfolio data display and add:
<div data-testid="portfolio-data">
  {/* existing portfolio display */}
</div>

// Find analyze button and add:
<button
  data-testid="analyze-button"
  onClick={handleAnalyze}
>
  Analyze Portfolio
</button>

// Find risk score display and add:
<div data-testid="risk-score">
  <h3>Risk Score: {riskScore}</h3>
  {/* existing risk score content */}
</div>

// Find risk score display component and add:
<div data-testid="risk-score-display">
  {/* risk score visualization */}
</div>
```

### Plaid Components

```jsx
// Find Plaid Link button and add:
<button
  data-testid="plaid-link-button"
  onClick={handlePlaidLink}
>
  Connect Bank Account
</button>

// Find Plaid modal and add:
<div data-testid="plaid-modal">
  {/* Plaid Link modal content */}
</div>

// Find connected accounts display and add:
<div data-testid="connected-accounts">
  {/* connected accounts list */}
</div>
```

### Chat Components

```jsx
// Find chat input and add:
<input
  data-testid="chat-input"
  type="text"
  value={chatInput}
  onChange={(e) => setChatInput(e.target.value)}
  placeholder="Ask me about your portfolio..."
/>

// Find chat send button and add:
<button
  data-testid="chat-send"
  onClick={handleChatSend}
>
  Send
</button>

// Find chat messages container and add:
<div data-testid="chat-messages">
  {messages.map((message, index) => (
    <div key={index} className={message.role === 'user' ? 'user-message' : 'ai-response'}>
      {message.content}
    </div>
  ))}
</div>
```

## Step 2: Create Test Helper Functions

Add these helper functions to your Cypress commands:

```javascript
// cypress/support/commands.js
Cypress.Commands.add('signIn', () => {
  // Mock Google sign-in for testing
  cy.window().then((win) => {
    win.postMessage({
      type: 'GOOGLE_SIGN_IN_SUCCESS',
      user: {
        name: 'Test User',
        email: 'test@example.com',
        picture: 'https://example.com/avatar.jpg'
      }
    }, '*');
  });
});

Cypress.Commands.add('uploadPortfolio', () => {
  cy.fixture('sample-portfolio.csv').then(fileContent => {
    cy.get('[data-testid="portfolio-upload"]').attachFile({
      fileContent,
      fileName: 'portfolio.csv',
      mimeType: 'text/csv'
    });
  });
});
```

## Step 3: Create Sample Test Data

```javascript
// cypress/fixtures/sample-portfolio.csv
Symbol,Shares,Price
AAPL,100,150.00
GOOGL,50,2500.00
MSFT,75,300.00
TSLA,25,800.00
```

## Step 4: Run Pre-Refactoring Tests

```bash
# Install testing dependencies if needed
npm install --save-dev @testing-library/react @testing-library/jest-dom cypress

# Run baseline tests to ensure everything works
npm run test:baseline
```

## Step 5: Commit Current State

```bash
# Add test IDs and commit
git add .
git commit -m "Add data-testid attributes for baseline testing"

# Create refactoring branch
git checkout -b frontend-refactoring

# Run full baseline test suite
npm run test:baseline
```

## Verification Checklist

Before starting refactoring, verify:
- ✅ All `data-testid` attributes added to App.js
- ✅ Cypress commands created for common actions
- ✅ Sample test data created
- ✅ Baseline tests pass completely
- ✅ Current state committed to git
- ✅ Refactoring branch created

## Common Test ID Patterns

Use these consistent patterns:

```javascript
// Buttons
data-testid="action-button"          // generic-button
data-testid="google-signin-button"   // specific-action-button
data-testid="plaid-link-button"      // service-action-button

// Containers
data-testid="section-name"           // landing-page, portfolio-data
data-testid="component-name"         // risk-score-display, chat-messages

// Inputs
data-testid="input-purpose"          // portfolio-upload, chat-input

// Status/Display
data-testid="status-type"            // user-profile, risk-score
```

## Mock API Responses

For reliable testing, mock external APIs:

```javascript
// cypress/support/commands.js
Cypress.Commands.add('mockGoogleAuth', () => {
  cy.intercept('POST', '/api/auth/google', {
    statusCode: 200,
    body: {
      user: {
        name: 'Test User',
        email: 'test@example.com',
        picture: 'https://example.com/avatar.jpg'
      }
    }
  });
});

Cypress.Commands.add('mockPortfolioAnalysis', () => {
  cy.intercept('POST', '/api/portfolio/analyze', {
    statusCode: 200,
    body: {
      riskScore: 6.5,
      analysis: {
        concentration: 7,
        volatility: 6,
        correlation: 6
      }
    }
  });
});

Cypress.Commands.add('mockPlaidLink', () => {
  cy.intercept('POST', '/api/plaid/create_link_token', {
    statusCode: 200,
    body: {
      link_token: 'mock-link-token'
    }
  });
});
```

## Next Steps

Once this setup is complete:
1. Run baseline tests to ensure 100% pass rate
2. Begin Phase 1 of the refactoring plan
3. Use the testing script to validate each phase
4. Proceed with confidence knowing you have a solid test foundation

This pre-refactoring setup ensures the testing script can properly validate your current functionality before any architectural changes begin. 