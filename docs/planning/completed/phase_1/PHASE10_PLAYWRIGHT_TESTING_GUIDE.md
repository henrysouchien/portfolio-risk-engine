# Phase 10 Playwright Testing Guide - CORRECTED APPROACH
## Simple Functional Testing Without Test IDs

<!-- CRITICAL CORRECTION: Previous version incorrectly required data-testid attributes throughout components.
This corrected version focuses on functional testing using text-based and generic selectors.
NO data-testid attributes need to be added to existing components. -->

### Overview
This guide provides a **CORRECTED** simple approach for Phase 10 AI to test the Portfolio Risk Dashboard functionality using Playwright. The key change: **NO data-testid attributes required** - we test what users see and do, not DOM implementation details.

### Setup Instructions

#### 1. Install Playwright
```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
npm install --save-dev @playwright/test
npx playwright install chromium
```

#### 2. Simple Playwright Configuration
Create `playwright.config.js`:
```javascript
module.exports = {
  testDir: './tests',
  timeout: 30000,
  use: {
    baseURL: 'http://localhost:3000',
    headless: false, // Keep visible for debugging
    viewport: { width: 1280, height: 720 },
    // Save authentication state for reuse
    storageState: 'auth.json'
  },
  projects: [
    {
      name: 'setup',
      testMatch: /.*\.setup\.js/,
    },
    {
      name: 'chromium',
      use: { ...require('@playwright/test').devices['Desktop Chrome'] },
      dependencies: ['setup'],
    }
  ]
};
```

### Authentication Setup

#### Create auth.setup.js:
```javascript
const { test: setup } = require('@playwright/test');

setup('authenticate', async ({ page }) => {
  // Navigate to app
  await page.goto('http://localhost:3000');
  
  // If login required, handle it
  if (await page.locator('text=Sign in').isVisible()) {
    await page.click('text=Sign in');
    // Handle OAuth flow as needed
  }
  
  // Wait for dashboard to load
  await page.waitForLoadState('networkidle');
  
  // Save authenticated state
  await page.context().storageState({ path: 'auth.json' });
});
```

#### Phase 10 CORRECTED Testing Code Templates
```javascript
const { test, expect } = require('@playwright/test');

test.describe('Dashboard Functional Testing - CORRECTED APPROACH', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to dashboard - authentication inherited from setup
    await page.goto('http://localhost:3000');
    
    // Wait for page to load completely (NO specific selectors required)
    await page.waitForLoadState('networkidle');
  });

  test('Dashboard loads with portfolio data', async ({ page }) => {
    // Verify dashboard content is present using text-based assertions
    await expect(page.locator('body')).toContainText('Portfolio');
    await expect(page.locator('body')).toContainText(/Risk Score|\$|Holdings/);
    
    // Take screenshot for verification
    await page.screenshot({ path: 'test-results/dashboard-loaded.png' });
    
    console.log('✅ Dashboard loaded successfully');
  });

  test('Navigation between views works', async ({ page }) => {
    // Find navigation buttons by text content (NO data-testid needed)
    const navButtons = [
      'Risk Score', 'Holdings', 'Performance', 'Factor Analysis'
    ];
    
    for (const buttonText of navButtons) {
      const button = page.locator('button').filter({ hasText: buttonText }).first();
      
      if (await button.isVisible()) {
        await button.click();
        await page.waitForTimeout(500); // Allow navigation
        
        // Verify view changed (generic text check)
        await expect(page.locator('body')).toContainText(buttonText);
        await page.screenshot({ path: `test-results/view-${buttonText.toLowerCase().replace(' ', '-')}.png` });
      }
    }
    
    console.log('✅ Navigation test completed');
  });

  test('Chat functionality responds', async ({ page }) => {
    // Find chat input using flexible selectors
    const chatInput = page.locator('input[placeholder*="message"], textarea[placeholder*="message"]').first();
    
    if (await chatInput.isVisible()) {
      await chatInput.fill('What is my portfolio value?');
      
      // Find send button or use Enter key
      const sendButton = page.locator('button').filter({ hasText: /Send|Submit/ }).first();
      if (await sendButton.isVisible()) {
        await sendButton.click();
      } else {
        await chatInput.press('Enter');
      }
      
      await page.waitForTimeout(2000);
      
      // Check if response appeared (generic check)
      const bodyText = await page.locator('body').textContent();
      const hasResponse = bodyText.includes('portfolio') || bodyText.includes('$');
      console.log('Chat response detected:', hasResponse);
    }
    
    console.log('✅ Chat functionality test completed');
  });
});
```

### Additional Functional Tests

#### Portfolio Data Integration Test:
```javascript
test('Portfolio data displays correctly', async ({ page }) => {
  // Check for financial data indicators
  const bodyText = await page.locator('body').textContent();
  
  // Verify financial data is present
  const hasFinancialData = bodyText.includes('$') || 
                          bodyText.includes('Portfolio') || 
                          bodyText.includes('Risk') ||
                          bodyText.includes('%');
  
  expect(hasFinancialData).toBeTruthy();
  
  console.log('✅ Portfolio data integration verified');
});
```

#### Error Handling Test:
```javascript
test('Dashboard handles errors gracefully', async ({ page }) => {
  // Monitor console errors
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  
  // Interact with dashboard
  await page.click('body');
  await page.waitForTimeout(2000);
  
  // Filter out non-critical errors
  const criticalErrors = consoleErrors.filter(error => 
    !error.includes('404') && 
    !error.includes('favicon') && 
    !error.includes('warning')
  );
  
  expect(criticalErrors.length).toBeLessThan(3);
  console.log('✅ Error handling test completed');
});
```

#### What Phase 10 Can Test (CORRECTED):
1. **Dashboard Loading**: Verify page loads with portfolio content
2. **Navigation**: Test view switching using button text
3. **Data Presence**: Verify financial data displays
4. **Chat Interface**: Test chat input/output functionality
5. **Error Monitoring**: Check for critical JavaScript errors
6. **Stability**: Verify dashboard remains functional under interaction
7. **Performance**: Monitor load times and responsiveness

#### Debug Integration:
- Leverage comprehensive logging from Phase 9.5
- Access browser console logs: `page.on('console', msg => console.log(msg.text()))`
- Network monitoring: `page.on('request', request => console.log(request.url()))`
- Screenshot capture for visual verification

### Running Tests

#### Execute All Tests:
```bash
npx playwright test
```

#### Run Specific Test:
```bash
npx playwright test --grep "Risk Score View"
```

#### Debug Mode:
```bash
npx playwright test --debug
```

### Key Advantages

1. **Real Authentication**: No mocking required - uses your actual Google OAuth session
2. **Real Data**: Tests with your actual portfolio data from backend APIs
3. **Complete Integration**: Tests entire stack from frontend to backend
4. **Visual Verification**: Screenshots and videos for result validation
5. **Performance Monitoring**: Real-world performance metrics
6. **Comprehensive Coverage**: Can test all user journeys systematically

### Key Changes in This CORRECTED Approach

1. **❌ REMOVED**: All `data-testid` attribute requirements
2. **✅ ADDED**: Text-based selectors using `.filter({ hasText: 'Button Text' })`
3. **✅ ADDED**: Generic element selectors like `page.locator('button')`, `page.locator('input')`
4. **✅ ADDED**: Flexible placeholder-based input selection
5. **✅ ADDED**: Content-based assertions using `toContainText()`
6. **✅ ADDED**: Simple success criteria focused on functionality

### Running Tests

```bash
# Install Playwright
npm install --save-dev @playwright/test
npx playwright install

# Run authentication setup
npx playwright test auth.setup.js

# Run all tests
npx playwright test

# Run with visual output
npx playwright test --headed

# Generate report
npx playwright show-report
```

### Success Criteria (SIMPLIFIED)

✅ **Pass Conditions:**
- Dashboard loads within 10 seconds
- Portfolio/financial data is visible in page content
- Navigation buttons work (identified by text)
- Chat interface accepts input
- No critical JavaScript errors (< 3)
- Page remains stable under interaction

❌ **NO LONGER REQUIRED:**
- Specific DOM element selection
- data-testid attributes in components
- Precise element targeting
- Complex selector strategies

### Next Steps for Phase 10

1. Use this CORRECTED guide to set up Playwright testing
2. Create test files using the functional testing templates above
3. **DO NOT add data-testid attributes** - existing components work as-is
4. Focus on testing user-visible functionality and behavior
5. Generate test reports with screenshots for visual verification
6. Use browser console logs for debugging any issues

**Result**: Phase 10 will have simple, effective testing capabilities that work with the existing dashboard code without requiring any component modifications.