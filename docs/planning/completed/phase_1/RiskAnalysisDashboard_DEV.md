# Portfolio Risk Analysis Dashboard - Development Summary

## Project Overview
Sophisticated portfolio risk analysis dashboard built with React, featuring real-time factor analysis, performance analytics, risk scoring, and conversational AI integration.

## Key Architecture Decisions

### Portfolio State Management
- **Portfolio Context Switching**: Dropdown supports Current Holdings, Saved Portfolios, and Scenarios
- **Scenario Support**: Database-backed scenarios (e.g., "Tech Reduced -20%", "Market Crash Stress Test")
- **State Flow**: Portfolio selection → Analyze Risk button → Complete analysis workflow

### Data Structure Alignment
**Real data integration completed for:**
- **Performance Analytics**: Actual returns, risk metrics, benchmark analysis (SPY), Sharpe ratios
- **Risk Settings**: Portfolio limits, concentration limits, variance limits, compliance status
- **Factor Analysis**: Portfolio-level betas, variance decomposition (62% factor/38% idiosyncratic), Euler percentages, industry exposures

### Chat Integration Features
- **Function Call Blocks**: Expandable blocks showing Claude's backend function calls with raw output
- **Portfolio Context Aware**: Chat operates within selected portfolio context
- **Dual Control**: Both manual portfolio switching AND chat-driven switching ("Switch to retirement portfolio")

## UI/UX Refinements Made

### Typography Consistency
- **Normalized text sizing** across all views (summary boxes, tables, headers)
- **Fixed hierarchy issues** where bold elements weren't properly aligned
- **Consistent font weights** throughout dashboard

### Visual Design
- **Color Palette**: Neutral grays with purposeful color use (red=violations, green=good, yellow=warnings)
- **Button Styling**: "Analyze Risk" button - subtle gray background with light shadow, not attention-grabbing
- **Visual Balance**: Proper spacing and alignment, especially in Risk Settings recommended limits section

### Layout Improvements
- **Information Flow**: Returns → Chart → Summary → Risk details (Performance Analytics)
- **Compliance First**: Risk Settings shows Compliance Status → Recommended Limits → Configuration
- **Chart Positioning**: Full-width performance charts, proper dividers in benchmark analysis

## Real Data Structures Used

### Factor Analysis Data
```
Portfolio-Level Betas: market(1.18), momentum(-0.33), value(0.13), industry(0.91), subindustry(0.78)
Variance Decomposition: 62% factor, 38% idiosyncratic
Factor Risk: Market 54%, Value 6%, Momentum 2%
Top Risk Contributors: MSCI(23.7%), STWD(20.2%), IT(17.6%), DSU(11.8%), NVDA(10.4%)
Industry Exposures: REM(30.2%), KCE(11.7%), XLK(7.8%), SOXX(5.4%)
Risk Violations: Factor Variance(61.51% > 30%), Market Variance(53.95% > 50%)
```

### Risk Limits Structure
```yaml
portfolio_limits:
  max_volatility: 0.4 (40%)
  max_loss: -0.25 (-25%)
concentration_limits:
  max_single_stock_weight: 0.4 (40%)
variance_limits:
  max_factor_contribution: 0.3 (30%)
  max_market_contribution: 0.5 (50%)
  max_industry_contribution: 0.3 (30%)
max_single_factor_loss: -0.1 (-10%)
```

## Component Structure
- **Main Dashboard**: Portfolio header, summary bar, sidebar navigation, content area, chat panel
- **Views**: Risk Score, Factor Analysis, Performance Analytics, Holdings, Analysis Report, Risk Settings
- **Chat Components**: Function call blocks, message history, portfolio context awareness

## Future Integration Points
- **Backend API**: Ready for Claude function call integration
- **Real-time Updates**: Dashboard can accept updates from chat-driven analysis
- **Scenario Management**: Database scenarios can be created/loaded via chat or UI
- **Dynamic Analysis**: "Analyze Risk" button triggers complete portfolio analysis workflow

## Development Notes
- Uses Recharts for visualizations
- Tailwind CSS for styling (core utility classes only)
- React hooks for state management
- No localStorage used (not supported in Claude.ai environment)
- Responsive design with mobile considerations

## Next Steps for New Claude Session
1. Continue refining Holdings view with real position data
2. Implement Analysis Report view with comprehensive summaries
3. Add advanced scenario comparison features
4. Integrate backend API for live Claude function calls
5. Add more sophisticated charts/visualizations for factor analysis

# Factor Analysis Dashboard - Integration Documentation

## Overview
The Factor Analysis Dashboard is a React component that provides comprehensive portfolio risk visualization through 8 main sections. This document details the exact data structures, field names, and integration requirements.

## Component Architecture

### Main Component: `FactorAnalysisTab`
- **Framework**: React with hooks (useState)
- **Styling**: Tailwind CSS
- **Charts**: Recharts library
- **Icons**: Lucide React

### Layout Structure
```
Factor Analysis Tab
├── Portfolio Risk Metrics (4-card grid)
├── Portfolio Variance Decomposition (stacked bar chart)
├── Risk-Limit & Industry Variance (2-column grid)
│   ├── Risk-Limit & Beta-Limit Checks (dot-plot gauges)
│   └── Industry Variance Contributions (list)
├── Risk Contributions Pareto Chart (bar + cumulative line)
├── Position Analysis Table (sortable data table)
├── Beta Exposure Checks (2-column grid with scrollable)
├── Correlation Matrix (triangular heatmap)
└── Industry & Stock Variance Treemap (rectangle sizing)
```

## Data Structure Requirements

### 1. Portfolio Risk Metrics (`mockRiskData`)
```javascript
const mockRiskData = {
  portfolioVolatility: 20.11,        // Number: Portfolio volatility as percentage
  portfolioVar: 15.42,               // Number: Value at Risk as percentage
  factorVariance: 61.51,             // Number: Factor variance contribution as percentage
  specificVariance: 38.49,           // Number: Specific variance contribution as percentage
  factorVar: 9.48,                   // Number: Factor VaR as percentage
  specificVar: 5.94                  // Number: Specific VaR as percentage
};
```

### 2. Portfolio Variance Decomposition
```javascript
const varianceDecomposition = [
  {
    category: "Factor Risk",         // String: Risk category name
    variance: 61.51,                 // Number: Variance percentage
    subFactors: [                    // Array: Breakdown by sub-factors
      { name: "market", value: 53.95 },      // String name, Number value
      { name: "momentum", value: 2.85 },
      { name: "value", value: 1.23 },
      { name: "industry", value: 2.48 },
      { name: "subindustry", value: 1.00 }
    ]
  },
  {
    category: "Specific Risk",
    variance: 38.49,
    subFactors: [
      { name: "idiosyncratic", value: 38.49 }
    ]
  }
];
```

### 3. Risk-Limit Checks (Dot-Plot Gauges)
```javascript
const riskLimitChecks = [
  {
    metric: "Portfolio Volatility",   // String: Metric name
    current: 20.11,                   // Number: Current value
    limit: 40.00,                     // Number: Risk limit threshold
    status: "PASS"                    // String: "PASS" or "FAIL"
  },
  {
    metric: "Factor Variance %",
    current: 61.51,
    limit: 30.00,
    status: "FAIL"
  },
  {
    metric: "Market Variance %",
    current: 53.95,
    limit: 50.00,
    status: "FAIL"
  },
  {
    metric: "Market β",
    current: 1.18,
    limit: 0.77,
    status: "FAIL"
  },
  {
    metric: "Momentum β",
    current: -0.33,
    limit: 0.79,
    status: "PASS"
  },
  {
    metric: "Value β",
    current: 0.13,
    limit: 0.55,
    status: "PASS"
  }
];
```

### 4. Industry Variance Contributions
```javascript
const industryVariance = [
  {
    industry: "REM (REIT - Mortgage)",  // String: Industry description
    variance: 30.2,                     // Number: Variance contribution percentage
    color: "purple-500"                 // String: Tailwind color class
  },
  {
    industry: "KCE (Asset Management)",
    variance: 11.7,
    color: "blue-500"
  },
  {
    industry: "DSU",
    variance: 11.0,
    color: "green-500"
  }
  // ... continue for all industries
];
```

### 5. Risk Contributions Pareto Data (`mockFactorData.riskContributions`)
```javascript
const riskContributions = [
  {
    ticker: "MSCI",                    // String: Stock ticker symbol
    contribution: 23.7,               // Number: Risk contribution percentage
    cumulative: 23.7                  // Number: Cumulative risk percentage (for Pareto line)
  },
  {
    ticker: "STWD",
    contribution: 20.2,
    cumulative: 43.9
  },
  {
    ticker: "IT",
    contribution: 17.6,
    cumulative: 61.5
  }
  // ... continue for all positions, sorted by contribution DESC
];
```

### 6. Position Analysis Table (`mockFactorData.positions`)
```javascript
const positions = [
  {
    ticker: "MSCI",                    // String: Stock ticker
    weight: 15.2,                      // Number: Portfolio weight percentage
    marketBeta: 1.25,                  // Number: Market beta
    momentumBeta: -0.15,               // Number: Momentum factor beta
    valueBeta: 0.08,                   // Number: Value factor beta
    industryBeta: 0.85,                // Number: Industry factor beta
    subindustryBeta: 0.72,             // Number: Sub-industry factor beta
    riskContribution: 23.7,            // Number: Risk contribution percentage
    factorRisk: 18.5,                  // Number: Factor risk percentage
    specificRisk: 5.2                  // Number: Specific risk percentage
  }
  // ... continue for all positions
];
```

### 7. Correlation Matrix
```javascript
const correlationMatrix = [
  {
    ticker: "DSU",                     // String: Row ticker
    correlations: [                    // Array: Correlation values
      1.00,    // vs DSU (diagonal)
      0.20,    // vs EQT
      0.12,    // vs IGIC
      0.59,    // vs IT
      // ... continue for all tickers in order
    ]
  }
  // ... one row per ticker
];

// Alternative structure for triangular matrix:
const triangularCorrelations = [
  {
    ticker: "DSU",
    correlations: [1.00, 0.20, 0.12, 0.59, ...]  // Full row
  },
  {
    ticker: "EQT", 
    correlations: [null, 1.00, -0.23, 0.01, ...]  // null values for upper triangle
  }
];
```

### 8. Beta Exposure Checks
```javascript
const betaExposureChecks = {
  mainFactors: [                       // Array: Primary factor betas
    {
      factor: "Market β",              // String: Factor name
      beta: 1.18,                      // Number: Current beta
      limit: 0.77,                     // Number: Beta limit
      status: "FAIL"                   // String: "PASS" or "FAIL"
    },
    {
      factor: "Momentum β",
      beta: -0.33,
      limit: 0.79,
      status: "PASS"
    },
    {
      factor: "Value β", 
      beta: 0.13,
      limit: 0.55,
      status: "PASS"
    }
  ],
  industryProxies: [                   // Array: Industry proxy betas
    {
      proxy: "DSU",                    // String: Industry proxy ticker
      beta: 0.25,                      // Number: Current beta
      limit: 0.50,                     // Number: Beta limit
      status: "PASS"                   // String: "PASS" or "FAIL"
    },
    {
      proxy: "REM",
      beta: 0.18,
      limit: 0.18,
      status: "PASS"
    }
    // ... continue for all industry proxies
  ]
};
```

### 9. Treemap Variance Data
```javascript
const treemapData = [
  {
    ticker: "MSCI",                    // String: Stock ticker
    variance: 23.7,                    // Number: Variance contribution percentage
    industry: "Technology",            // String: Industry classification
    industryColor: "blue-600",         // String: Tailwind color for industry
    size: {                           // Object: Rectangle positioning
      left: "0%",                     // String: CSS left position
      top: "0%",                      // String: CSS top position  
      width: "35%",                   // String: CSS width
      height: "60%"                   // String: CSS height
    }
  }
  // ... continue for all positions
];
```

## Color Schemes & Constants

### Chart Colors (`CHART_COLORS`)
```javascript
const CHART_COLORS = {
  primary: '#3B82F6',      // Blue - main chart color
  secondary: '#10B981',    // Green - secondary elements
  danger: '#EF4444',       // Red - violations/alerts
  warning: '#F59E0B',      // Orange - warnings
  muted: '#6B7280'         // Gray - muted elements
};
```

### Status Color Mapping
- **PASS**: Green (`bg-green-100 text-green-800`, `bg-green-500`)
- **FAIL**: Red (`bg-red-100 text-red-800`, `bg-red-500`)

### Industry Color Mapping
```javascript
const industryColors = {
  "Technology": "blue",
  "REIT": "purple", 
  "Energy": "green",
  "Financial": "orange",
  "Others": "gray"
};
```

## Integration Checklist

### Data Transformation Requirements
1. **Field Mapping**: Map your API field names to expected names
2. **Type Conversion**: Ensure percentages are numbers (not strings)
3. **Status Calculation**: Derive "PASS"/"FAIL" from current vs. limit values
4. **Sorting**: Risk contributions must be sorted DESC by contribution
5. **Cumulative Calculation**: Calculate running totals for Pareto chart
6. **Color Assignment**: Map industries to consistent color schemes

### API Integration Points
1. **Portfolio Metrics Endpoint** → `mockRiskData`
2. **Factor Analysis Endpoint** → Variance decomposition
3. **Risk Limits Endpoint** → Limit checks data
4. **Holdings Endpoint** → Position analysis table
5. **Correlations Endpoint** → Correlation matrix
6. **Beta Exposures Endpoint** → Beta exposure checks

### Error Handling Requirements
- Loading states for each section
- Fallback values for missing data
- Error boundaries for chart failures
- Data validation before rendering

### Performance Considerations
- Correlation matrix: O(n²) for n positions
- Treemap: Complex positioning calculations
- Large position tables: Consider pagination/virtualization
- Real-time updates: Debounce API calls

## Dependencies

### Required NPM Packages
```json
{
  "react": "^18.0.0",
  "recharts": "^2.8.0", 
  "lucide-react": "^0.263.1",
  "tailwindcss": "^3.3.0"
}
```

### Tailwind Configuration
Ensure all color classes are available:
- `bg-{color}-{shade}` for backgrounds
- `text-{color}-{shade}` for text
- Colors: red, green, blue, purple, orange, yellow, pink, indigo, teal, gray

## Usage Example

```jsx
import { FactorAnalysisTab } from './components/FactorAnalysisTab';

// Transform your API data to match expected structure
const transformedData = {
  riskMetrics: adaptRiskMetrics(apiRiskData),
  positions: adaptPositions(apiPositions),
  correlations: adaptCorrelations(apiCorrelations),
  // ... other data sources
};

function App() {
  return (
    <div className="portfolio-dashboard">
      <FactorAnalysisTab data={transformedData} />
    </div>
  );
}
```

## Notes for Implementation

1. **Mock Data Replacement**: Replace all `mockRiskData` and `mockFactorData` references with real API calls
2. **State Management**: Add loading/error states as needed
3. **Responsive Design**: Dashboard is responsive but test on your target screen sizes
4. **Data Refresh**: Implement refresh mechanisms for real-time updates
5. **Customization**: Colors, labels, and thresholds can be customized via props or config files

This dashboard provides a comprehensive view of portfolio risk factor analysis with professional-grade visualizations suitable for institutional risk management.

# Complete Portfolio Risk Dashboard - Integration Documentation

## Overview
The Portfolio Risk Dashboard is a comprehensive React application with 4 main tabs providing portfolio analysis, risk assessment, and performance tracking. This document details ALL data structures, field names, and integration requirements across the entire frontend.

## Application Architecture

### Main Application Structure
```
Portfolio Risk Dashboard
├── Dashboard Tab (Overview + Quick Actions)
├── Factor Analysis Tab (Risk Factor Breakdown)
├── Risk Score Tab (Risk Assessment & Scenarios)
└── Performance Analytics Tab (Returns & Attribution)
```

### Technology Stack
- **Framework**: React 18+ with hooks
- **Styling**: Tailwind CSS
- **Charts**: Recharts library
- **Icons**: Lucide React
- **State Management**: React useState/useEffect

---

## TAB 1: DASHBOARD (Overview)

### Layout Structure
```
Dashboard Tab
├── Portfolio Overview (4-card metrics grid)
├── Asset Allocation (pie chart)
├── Risk Overview (3-card metrics grid)
├── Recent Activity (transaction list)
├── Quick Actions (action buttons grid)
└── Performance Chart (line chart)
```

### Data Requirements

#### 1. Portfolio Overview Metrics
```javascript
const portfolioOverview = {
  totalValue: 2847293.45,           // Number: Total portfolio value in currency
  dayChange: 12847.23,              // Number: Daily change in currency
  dayChangePercent: 0.45,           // Number: Daily change as percentage (0.45 = 0.45%)
  totalReturn: 184729.12,           // Number: Total return in currency
  totalReturnPercent: 6.95,         // Number: Total return as percentage
  cashPosition: 145820.33,          // Number: Cash position in currency
  cashPercent: 5.12,                // Number: Cash as percentage of portfolio
  positionCount: 14,                // Number: Total number of positions
  lastUpdated: "2025-01-23T15:30:00Z" // String: ISO timestamp of last update
};
```

#### 2. Asset Allocation Data
```javascript
const assetAllocation = [
  {
    category: "Equities",            // String: Asset category name
    value: 2405847.21,               // Number: Value in currency
    percentage: 84.5,                // Number: Percentage of total portfolio
    color: "#3B82F6",                // String: Hex color for chart
    subcategories: [                 // Array: Breakdown by subcategory
      {
        name: "US Large Cap",        // String: Subcategory name
        value: 1823420.15,           // Number: Value in currency
        percentage: 64.0             // Number: Percentage of total
      },
      {
        name: "Technology",
        value: 582427.06,
        percentage: 20.5
      }
    ]
  },
  {
    category: "Fixed Income",
    value: 285647.18,
    percentage: 10.0,
    color: "#10B981",
    subcategories: [
      {
        name: "Government Bonds",
        value: 171388.31,
        percentage: 6.0
      },
      {
        name: "Corporate Bonds", 
        value: 114258.87,
        percentage: 4.0
      }
    ]
  },
  {
    category: "Alternatives",
    value: 155979.06,
    percentage: 5.5,
    color: "#F59E0B",
    subcategories: [
      {
        name: "REITs",
        value: 85536.48,
        percentage: 3.0
      },
      {
        name: "Commodities",
        value: 70442.58,
        percentage: 2.5
      }
    ]
  }
];
```

#### 3. Risk Overview Metrics
```javascript
const riskOverview = {
  portfolioVolatility: 18.45,       // Number: Portfolio volatility percentage
  valueAtRisk: 142847.23,           // Number: VaR in currency (95% confidence)
  maxDrawdown: -8.32,               // Number: Maximum drawdown percentage (negative)
  sharpeRatio: 1.24,                // Number: Sharpe ratio
  beta: 1.18,                       // Number: Portfolio beta vs benchmark
  correlationToMarket: 0.85,        // Number: Correlation to market (0-1)
  trackingError: 3.42,              // Number: Tracking error percentage
  informationRatio: 0.67            // Number: Information ratio
};
```

#### 4. Recent Activity (Transactions)
```javascript
const recentActivity = [
  {
    id: "txn_001",                   // String: Unique transaction ID
    type: "BUY",                     // String: "BUY", "SELL", "DIVIDEND", "SPLIT"
    ticker: "MSCI",                  // String: Stock ticker (null for cash transactions)
    name: "MSCI Inc",                // String: Security name
    quantity: 150,                   // Number: Number of shares (null for dividends)
    price: 542.18,                   // Number: Price per share
    amount: 81327.00,                // Number: Total transaction amount
    fees: 12.50,                     // Number: Transaction fees
    date: "2025-01-23T10:15:00Z",    // String: ISO timestamp
    status: "SETTLED",               // String: "PENDING", "SETTLED", "FAILED"
    account: "Main Portfolio"        // String: Account name
  },
  {
    id: "txn_002",
    type: "DIVIDEND",
    ticker: "V",
    name: "Visa Inc",
    quantity: null,
    price: null,
    amount: 245.67,
    fees: 0,
    date: "2025-01-22T14:30:00Z",
    status: "SETTLED",
    account: "Main Portfolio"
  }
];
```

#### 5. Performance Chart Data
```javascript
const performanceChart = [
  {
    date: "2024-01-01",              // String: Date in YYYY-MM-DD format
    portfolioValue: 2658420.33,      // Number: Total portfolio value
    benchmarkValue: 2650000.00,      // Number: Benchmark value (normalized to same start)
    cashFlow: 0,                     // Number: Net cash flow on this date
    dailyReturn: 0.0,                // Number: Daily return percentage
    cumulativeReturn: 0.0            // Number: Cumulative return since inception
  },
  {
    date: "2024-01-02", 
    portfolioValue: 2672841.45,
    benchmarkValue: 2663200.00,
    cashFlow: 0,
    dailyReturn: 0.54,
    cumulativeReturn: 0.54
  }
  // ... daily data points for specified time period
];
```

#### 6. Quick Actions Configuration
```javascript
const quickActions = [
  {
    id: "rebalance",                 // String: Unique action ID
    title: "Rebalance Portfolio",   // String: Action title
    description: "Optimize allocations", // String: Action description
    icon: "Scale",                   // String: Lucide icon name
    color: "blue",                   // String: Color theme
    enabled: true,                   // Boolean: Whether action is available
    badge: null                      // String|null: Optional badge text
  },
  {
    id: "risk_check",
    title: "Run Risk Check", 
    description: "Analyze current risk",
    icon: "Shield",
    color: "red",
    enabled: true,
    badge: "3 Issues"
  },
  {
    id: "tax_loss",
    title: "Tax Loss Harvesting",
    description: "Identify opportunities", 
    icon: "Receipt",
    color: "green",
    enabled: true,
    badge: null
  },
  {
    id: "add_funds",
    title: "Add Funds",
    description: "Deposit to account",
    icon: "Plus",
    color: "purple", 
    enabled: true,
    badge: null
  }
];
```

---

## TAB 2: FACTOR ANALYSIS (Detailed in previous documentation)

*[Previous Factor Analysis documentation remains complete and accurate]*

---

## TAB 3: RISK SCORE 

### Layout Structure
```
Risk Score Tab  
├── Risk Score Summary (large score display)
├── Risk Components Breakdown (radar chart)
├── Risk Limits Status (status cards grid)
├── Scenario Analysis (stress test results)
├── Risk Attribution (bar chart)
└── Risk Recommendations (action items list)
```

### Data Requirements

#### 1. Risk Score Summary
```javascript
const riskScoreSummary = {
  overallScore: 73,                 // Number: Overall risk score (0-100)
  scoreChange: -2,                  // Number: Change from previous period
  riskLevel: "MODERATE",            // String: "LOW", "MODERATE", "HIGH", "EXTREME"
  confidenceLevel: 89,              // Number: Confidence in score (0-100)
  lastCalculated: "2025-01-23T14:30:00Z", // String: ISO timestamp
  components: {                     // Object: Breakdown by risk component
    market: 78,                     // Number: Market risk score (0-100)
    credit: 45,                     // Number: Credit risk score  
    liquidity: 23,                  // Number: Liquidity risk score
    concentration: 89,              // Number: Concentration risk score
    operational: 12                 // Number: Operational risk score
  }
};
```

#### 2. Risk Components (Radar Chart)
```javascript
const riskComponents = [
  {
    component: "Market Risk",        // String: Risk component name
    current: 78,                     // Number: Current score (0-100)
    target: 65,                      // Number: Target score
    benchmark: 70,                   // Number: Benchmark/peer score
    weight: 0.35,                    // Number: Weight in overall score (0-1)
    trend: "INCREASING"              // String: "INCREASING", "DECREASING", "STABLE"
  },
  {
    component: "Credit Risk",
    current: 45,
    target: 50,
    benchmark: 48,
    weight: 0.20,
    trend: "STABLE"
  },
  {
    component: "Liquidity Risk",
    current: 23,
    target: 30,
    benchmark: 35,
    weight: 0.15,
    trend: "DECREASING"
  },
  {
    component: "Concentration Risk", 
    current: 89,
    target: 60,
    benchmark: 55,
    weight: 0.25,
    trend: "INCREASING"
  },
  {
    component: "Operational Risk",
    current: 12,
    target: 20,
    benchmark: 25,
    weight: 0.05,
    trend: "STABLE"
  }
];
```

#### 3. Risk Limits Status
```javascript
const riskLimitsStatus = [
  {
    category: "Portfolio Level",     // String: Limit category
    limits: [                       // Array: Individual limits
      {
        name: "Total VaR",          // String: Limit name
        current: 142847.23,         // Number: Current value
        limit: 150000.00,           // Number: Limit threshold
        utilization: 95.2,          // Number: Utilization percentage
        status: "WARNING",          // String: "OK", "WARNING", "BREACH"
        unit: "USD"                 // String: Value unit
      },
      {
        name: "Portfolio Volatility",
        current: 18.45,
        limit: 25.00,
        utilization: 73.8,
        status: "OK", 
        unit: "%"
      }
    ]
  },
  {
    category: "Position Level",
    limits: [
      {
        name: "Single Position Limit",
        current: 25.3,
        limit: 20.0,
        utilization: 126.5,
        status: "BREACH",
        unit: "%"
      },
      {
        name: "Sector Concentration",
        current: 45.2,
        limit: 50.0,
        utilization: 90.4,
        status: "WARNING",
        unit: "%"
      }
    ]
  }
];
```

#### 4. Scenario Analysis
```javascript
const scenarioAnalysis = [
  {
    scenario: "Market Crash",        // String: Scenario name
    description: "Broad market decline of 20%", // String: Scenario description
    probability: 15,                 // Number: Probability percentage
    impact: {                       // Object: Expected impact
      portfolioReturn: -18.5,        // Number: Portfolio return percentage
      dollarImpact: -526743.12,      // Number: Dollar impact
      worstPosition: "MSCI",         // String: Most impacted position
      worstPositionImpact: -28.3     // Number: Worst position impact percentage
    },
    timeframe: "1M",                 // String: Time horizon ("1M", "3M", "1Y")
    confidence: 78                   // Number: Confidence in estimate (0-100)
  },
  {
    scenario: "Interest Rate Spike",
    description: "Federal funds rate increases 2%",
    probability: 25,
    impact: {
      portfolioReturn: -8.2,
      dollarImpact: -233600.45,
      worstPosition: "STWD",
      worstPositionImpact: -15.7
    },
    timeframe: "6M",
    confidence: 85
  },
  {
    scenario: "Tech Sector Rotation",
    description: "Technology sector underperforms",
    probability: 35,
    impact: {
      portfolioReturn: -12.4,
      dollarImpact: -352984.39,
      worstPosition: "NVDA",
      worstPositionImpact: -22.1
    },
    timeframe: "3M",
    confidence: 72
  }
];
```

#### 5. Risk Attribution
```javascript
const riskAttribution = [
  {
    source: "Single Stock Risk",     // String: Risk source
    contribution: 45.2,              // Number: Contribution to total risk (%)
    positions: [                     // Array: Top contributing positions
      {
        ticker: "DSU",               // String: Position ticker
        contribution: 18.3,          // Number: Individual contribution (%)
        reason: "High volatility"    // String: Primary risk driver
      },
      {
        ticker: "MSCI", 
        contribution: 15.8,
        reason: "Large position size"
      }
    ]
  },
  {
    source: "Sector Concentration",
    contribution: 28.7,
    positions: [
      {
        sector: "Technology",        // String: Sector name (instead of ticker)
        contribution: 28.7,
        reason: "Over-weighted allocation"
      }
    ]
  },
  {
    source: "Market Beta",
    contribution: 26.1,
    positions: [
      {
        factor: "Market Exposure",   // String: Factor name
        contribution: 26.1,
        reason: "High beta to market"
      }
    ]
  }
];
```

#### 6. Risk Recommendations  
```javascript
const riskRecommendations = [
  {
    id: "rec_001",                   // String: Unique recommendation ID
    priority: "HIGH",                // String: "HIGH", "MEDIUM", "LOW"
    category: "Position Sizing",     // String: Recommendation category
    title: "Reduce DSU Position",    // String: Recommendation title
    description: "DSU position exceeds 20% limit and contributes disproportionate risk", // String: Detailed description
    impact: {                       // Object: Expected impact if implemented
      riskReduction: 12.5,          // Number: Risk reduction percentage
      returnImpact: -0.3,           // Number: Expected return impact
      costEstimate: 2500.00         // Number: Implementation cost
    },
    actions: [                      // Array: Specific actions to take
      "Sell 40% of DSU position",
      "Reinvest proceeds in diversified ETF",
      "Monitor for rebalancing opportunities"
    ],
    timeframe: "1W",                // String: Recommended timeframe
    status: "PENDING"               // String: "PENDING", "IN_PROGRESS", "COMPLETED"
  },
  {
    id: "rec_002",
    priority: "MEDIUM",
    category: "Diversification",
    title: "Add International Exposure", 
    description: "Portfolio lacks geographic diversification",
    impact: {
      riskReduction: 8.2,
      returnImpact: 0.1,
      costEstimate: 150.00
    },
    actions: [
      "Allocate 15% to international developed markets",
      "Consider emerging markets exposure"
    ],
    timeframe: "1M",
    status: "PENDING"
  }
];
```

---

## TAB 4: PERFORMANCE ANALYTICS

### Layout Structure
```
Performance Analytics Tab
├── Performance Summary (metrics cards)
├── Performance Chart (multi-line time series) 
├── Return Attribution (waterfall chart)
├── Risk-Adjusted Returns (scatter plot)
├── Benchmark Comparison (comparative table)
└── Performance Analytics (detailed breakdown)
```

### Data Requirements

#### 1. Performance Summary
```javascript
const performanceSummary = {
  periods: {                        // Object: Returns by time period
    "1D": {
      portfolioReturn: 0.45,        // Number: Portfolio return percentage
      benchmarkReturn: 0.38,        // Number: Benchmark return percentage
      activeReturn: 0.07,           // Number: Active return (portfolio - benchmark)
      volatility: 1.24              // Number: Volatility for period
    },
    "1W": {
      portfolioReturn: 2.18,
      benchmarkReturn: 1.95,
      activeReturn: 0.23,
      volatility: 2.87
    },
    "1M": {
      portfolioReturn: 3.42,
      benchmarkReturn: 2.89,
      activeReturn: 0.53,
      volatility: 4.15
    },
    "3M": {
      portfolioReturn: 8.76,
      benchmarkReturn: 7.23,
      activeReturn: 1.53,
      volatility: 7.92
    },
    "1Y": {
      portfolioReturn: 12.45,
      benchmarkReturn: 10.28,
      activeReturn: 2.17,
      volatility: 15.33
    },
    "3Y": {
      portfolioReturn: 28.92,       // Number: Annualized for multi-year periods
      benchmarkReturn: 24.16,
      activeReturn: 4.76,
      volatility: 16.84
    },
    "5Y": {
      portfolioReturn: 42.18,
      benchmarkReturn: 35.94,
      activeReturn: 6.24,
      volatility: 17.25
    },
    "ITD": {                        // Inception to date
      portfolioReturn: 68.45,
      benchmarkReturn: 58.72,
      activeReturn: 9.73,
      volatility: 18.15
    }
  },
  riskMetrics: {                    // Object: Risk-adjusted performance metrics
    sharpeRatio: 1.24,              // Number: Sharpe ratio
    informationRatio: 0.67,         // Number: Information ratio
    sortino: 1.56,                  // Number: Sortino ratio
    maxDrawdown: -8.32,             // Number: Maximum drawdown percentage
    calmar: 1.49,                   // Number: Calmar ratio
    beta: 1.18,                     // Number: Beta vs benchmark
    alpha: 2.45,                    // Number: Alpha vs benchmark
    trackingError: 3.42             // Number: Tracking error percentage
  }
};
```

#### 2. Performance Chart Time Series
```javascript
const performanceTimeSeries = [
  {
    date: "2024-01-01",              // String: Date in YYYY-MM-DD format
    portfolioValue: 2658420.33,      // Number: Portfolio value
    benchmarkValue: 2650000.00,      // Number: Benchmark value (normalized)
    portfolioCumReturn: 0.0,         // Number: Cumulative return since start
    benchmarkCumReturn: 0.0,         // Number: Benchmark cumulative return
    activeReturn: 0.0,               // Number: Active return (portfolio - benchmark)
    rollingSharpe: null,             // Number|null: 252-day rolling Sharpe ratio
    rollingVol: null,                // Number|null: 252-day rolling volatility
    drawdown: 0.0                    // Number: Drawdown from peak
  },
  {
    date: "2024-01-02",
    portfolioValue: 2672841.45,
    benchmarkValue: 2663200.00,
    portfolioCumReturn: 0.54,
    benchmarkCumReturn: 0.50,
    activeReturn: 0.04,
    rollingSharpe: null,
    rollingVol: null,
    drawdown: 0.0
  }
  // ... daily data points
];
```

#### 3. Return Attribution (Waterfall Chart)
```javascript
const returnAttribution = {
  totalReturn: 3.42,               // Number: Total portfolio return for period
  benchmark: 2.89,                 // Number: Benchmark return
  components: [                    // Array: Attribution components (order matters for waterfall)
    {
      name: "Security Selection",   // String: Attribution component name
      contribution: 0.78,          // Number: Contribution to return
      description: "Stock picking effect" // String: Component description
    },
    {
      name: "Asset Allocation",
      contribution: 0.45,
      description: "Sector/asset class weights"
    },
    {
      name: "Timing",
      contribution: -0.12,
      description: "Entry/exit timing"
    },
    {
      name: "Currency",
      contribution: 0.03,
      description: "Currency exposure effect"
    },
    {
      name: "Fees & Costs",
      contribution: -0.61,
      description: "Transaction costs and fees"
    }
  ],
  activeReturn: 0.53               // Number: Total active return (sum of components)
};
```

#### 4. Risk-Adjusted Returns (Scatter Plot)
```javascript
const riskAdjustedReturns = [
  {
    name: "Portfolio",               // String: Data point name
    return: 12.45,                   // Number: Annualized return percentage
    volatility: 15.33,               // Number: Annualized volatility percentage
    sharpe: 1.24,                    // Number: Sharpe ratio
    category: "Portfolio",           // String: Category for coloring
    size: 100                        // Number: Bubble size (for bubble chart)
  },
  {
    name: "Benchmark",
    return: 10.28,
    volatility: 14.85,
    sharpe: 0.98,
    category: "Benchmark",
    size: 100
  },
  {
    name: "Top Quartile",           // Peer group data points
    return: 13.82,
    volatility: 16.24,
    sharpe: 1.35,
    category: "Peer",
    size: 80
  },
  {
    name: "Median",
    return: 11.45,
    volatility: 15.67,
    sharpe: 1.05,
    category: "Peer", 
    size: 80
  },
  {
    name: "Bottom Quartile",
    return: 8.93,
    volatility: 17.12,
    sharpe: 0.72,
    category: "Peer",
    size: 80
  }
];
```

#### 5. Benchmark Comparison Table
```javascript
const benchmarkComparison = [
  {
    metric: "Total Return",          // String: Performance metric name
    portfolio: 12.45,                // Number: Portfolio value
    benchmark: 10.28,                // Number: Primary benchmark value
    difference: 2.17,                // Number: Difference (portfolio - benchmark)
    percentile: 75,                  // Number: Percentile rank vs peers (0-100)
    unit: "%"                        // String: Value unit
  },
  {
    metric: "Volatility",
    portfolio: 15.33,
    benchmark: 14.85,
    difference: 0.48,
    percentile: 55,
    unit: "%"
  },
  {
    metric: "Sharpe Ratio",
    portfolio: 1.24,
    benchmark: 0.98,
    difference: 0.26,
    percentile: 80,
    unit: ""
  },
  {
    metric: "Max Drawdown",
    portfolio: -8.32,
    benchmark: -9.45,
    difference: 1.13,                // Positive difference = better (less negative)
    percentile: 65,
    unit: "%"
  },
  {
    metric: "Information Ratio",
    portfolio: 0.67,
    benchmark: null,                 // Not applicable for benchmark
    difference: null,
    percentile: 70,
    unit: ""
  }
];
```

#### 6. Performance Analytics Breakdown
```javascript
const performanceAnalytics = {
  positionContribution: [           // Array: Individual position contributions
    {
      ticker: "MSCI",               // String: Position ticker
      weight: 15.2,                 // Number: Average weight during period
      return: 18.45,                // Number: Security return for period
      contribution: 2.81,           // Number: Contribution to portfolio return
      activeWeight: 3.2,            // Number: Active weight vs benchmark
      activeReturn: 5.23,           // Number: Active return vs benchmark
      attribution: 0.78             // Number: Attribution effect
    },
    {
      ticker: "STWD",
      weight: 12.8,
      return: -5.23,
      contribution: -0.67,
      activeWeight: 12.8,           // Not in benchmark
      activeReturn: -5.23,
      attribution: -0.67
    }
    // ... all positions
  ],
  sectorContribution: [             // Array: Sector-level contributions
    {
      sector: "Technology",         // String: Sector name
      portfolioWeight: 45.2,        // Number: Portfolio weight in sector
      benchmarkWeight: 38.5,        // Number: Benchmark weight in sector
      activeWeight: 6.7,            // Number: Active weight (portfolio - benchmark)
      return: 15.28,                // Number: Sector return
      contribution: 6.90,           // Number: Contribution to portfolio return
      attribution: 1.02             // Number: Attribution vs benchmark
    },
    {
      sector: "Financials",
      portfolioWeight: 12.3,
      benchmarkWeight: 15.2,
      activeWeight: -2.9,
      return: 8.45,
      contribution: 1.04,
      attribution: -0.25
    }
    // ... all sectors
  ],
  monthlyReturns: [                 // Array: Monthly return data
    {
      month: "2024-01",             // String: Month in YYYY-MM format
      portfolioReturn: 2.45,        // Number: Monthly portfolio return
      benchmarkReturn: 1.89,        // Number: Monthly benchmark return
      activeReturn: 0.56,           // Number: Monthly active return
      rank: 15,                     // Number: Rank vs peer universe
      percentile: 85                // Number: Percentile vs peers
    }
    // ... monthly data for time period
  ]
};
```

---

## GLOBAL DATA STRUCTURES

### User Profile & Settings
```javascript
const userProfile = {
  userId: "user_12345",             // String: Unique user identifier
  name: "John Doe",                 // String: User display name  
  email: "john.doe@example.com",    // String: User email
  role: "PORTFOLIO_MANAGER",        // String: User role/permissions
  preferences: {                    // Object: User preferences
    currency: "USD",                // String: Display currency
    timezone: "America/New_York",   // String: Timezone
    riskTolerance: "MODERATE",      // String: Risk tolerance level
    benchmarkId: "SPY",             // String: Default benchmark
    refreshInterval: 300            // Number: Data refresh interval (seconds)
  },
  permissions: [                    // Array: User permissions
    "VIEW_PORTFOLIO",
    "EDIT_ALLOCATIONS", 
    "RUN_ANALYSIS",
    "EXPORT_DATA"
  ]
};
```

### Market Data Context
```javascript
const marketContext = {
  marketStatus: "OPEN",             // String: "OPEN", "CLOSED", "PRE_MARKET", "AFTER_HOURS"
  lastUpdate: "2025-01-23T15:45:00Z", // String: Last market data update
  indices: {                        // Object: Major market indices
    "SPY": {
      value: 442.18,                // Number: Current value
      change: 2.34,                 // Number: Daily change
      changePercent: 0.53           // Number: Daily change percentage
    },
    "QQQ": {
      value: 378.45,
      change: -1.23,
      changePercent: -0.32
    },
    "VIX": {
      value: 18.45,
      change: 0.78,
      changePercent: 4.42
    }
  },
  alerts: [                         // Array: Market alerts/news
    {
      id: "alert_001",              // String: Alert ID
      type: "MARKET_NEWS",          // String: Alert type
      severity: "MEDIUM",           // String: "LOW", "MEDIUM", "HIGH"
      title: "Fed Meeting Today",   // String: Alert title
      description: "Federal Reserve meeting scheduled at 2PM EST", // String: Description
      timestamp: "2025-01-23T14:00:00Z", // String: Alert timestamp
      relevantTickers: ["SPY", "TLT"] // Array: Relevant tickers
    }
  ]
};
```

### Application State
```javascript
const appState = {
  activeTab: "dashboard",           // String: Currently active tab
  loadingStates: {                  // Object: Loading states by component
    portfolio: false,               // Boolean: Portfolio data loading
    performance: true,              // Boolean: Performance data loading
    risk: false                     // Boolean: Risk data loading
  },
  errors: {                         // Object: Error states by component
    portfolio: null,                // String|null: Error message
    performance: null,
    risk: "Failed to load risk data" // String|null: Error message
  },
  lastRefresh: "2025-01-23T15:30:00Z", // String: Last successful data refresh
  connectionStatus: "CONNECTED"     // String: "CONNECTED", "DISCONNECTED", "RECONNECTING"
};
```

---

## API INTEGRATION REQUIREMENTS

### Authentication
```javascript
// Required headers for all API calls
const headers = {
  'Authorization': 'Bearer ' + jwt_token,
  'Content-Type': 'application/json',
  'X-Client-Version': '1.0.0'
};
```

### API Endpoints Map
```javascript
const apiEndpoints = {
  // Dashboard data
  portfolio: '/api/v1/portfolio/overview',
  assetAllocation: '/api/v1/portfolio/allocation',
  performance: '/api/v1/portfolio/performance',
  activity: '/api/v1/portfolio/activity',
  
  // Factor Analysis data
  factorAnalysis: '/api/v1/risk/factor-analysis',
  correlations: '/api/v1/risk/correlations',
  riskContributions: '/api/v1/risk/contributions',
  betaExposures: '/api/v1/risk/beta-exposures',
  
  // Risk Score data
  riskScore: '/api/v1/risk/score',
  scenarios: '/api/v1/risk/scenarios',
  limits: '/api/v1/risk/limits',
  recommendations: '/api/v1/risk/recommendations',
  
  // Performance Analytics data
  performanceAnalytics: '/api/v1/performance/analytics',
  attribution: '/api/v1/performance/attribution',
  benchmarkComparison: '/api/v1/performance/benchmark',
  
  // Market data
  marketData: '/api/v1/market/indices',
  alerts: '/api/v1/market/alerts'
};
```

### Error Handling Standards
```javascript
const errorHandling = {
  networkError: {
    message: "Unable to connect to server",
    action: "retry",
    fallback: "cached_data"
  },
  authError: {
    message: "Session expired",
    action: "redirect_login",
    fallback: null
  },
  dataError: {
    message: "Invalid data received",
    action: "log_error",
    fallback: "default_values"
  },
  rateLimit: {
    message: "Too many requests",
    action: "backoff_retry",
    fallback: "cached_data"
  }
};
```

### Data Validation Schema
```javascript
const validationRules = {
  required: ['ticker', 'weight', 'value'],     // Required fields
  numberFields: ['weight', 'return', 'beta'],  // Must be numbers
  percentageFields: ['weight', 'return'],      // Must be 0-100 (or appropriate range)
  dateFields: ['lastUpdated', 'date'],         // Must be valid ISO dates
  enumFields: {                               // Must match specific values
    status: ['PASS', 'FAIL', 'WARNING'],
    type: ['BUY', 'SELL', 'DIVIDEND', 'SPLIT']
  }
};
```

---

## IMPLEMENTATION CHECKLIST

### Phase 1: Core Data Integration
- [ ] Set up API client with authentication
- [ ] Implement data fetching for Dashboard tab
- [ ] Add loading states and error handling
- [ ] Create data transformation layer
- [ ] Test with real API responses

### Phase 2: Advanced Features  
- [ ] Integrate Factor Analysis data
- [ ] Implement Risk Score calculations
- [ ] Add Performance Analytics data
- [ ] Test all visualizations with real data
- [ ] Optimize performance for large datasets

### Phase 3: Production Readiness
- [ ] Add comprehensive error boundaries
- [ ] Implement data caching strategy  
- [ ] Add real-time data updates
- [ ] Performance testing and optimization
- [ ] Security audit and testing

### Phase 4: Enhancement
- [ ] Add data export capabilities
- [ ] Implement user customization
- [ ] Add advanced filtering/sorting
- [ ] Mobile responsiveness testing
- [ ] Accessibility compliance

---

## DEPENDENCIES & SETUP

### Required NPM Packages
```json
{
  "react": "^18.0.0",
  "react-dom": "^18.0.0", 
  "recharts": "^2.8.0",
  "lucide-react": "^0.263.1",
  "tailwindcss": "^3.3.0",
  "date-fns": "^2.30.0",
  "numeral": "^2.0.6"
}
```

### Environment Variables
```bash
REACT_APP_API_BASE_URL=https://api.yourcompany.com
REACT_APP_WS_URL=wss://ws.yourcompany.com
REACT_APP_AUTH_DOMAIN=auth.yourcompany.com
REACT_APP_ENVIRONMENT=production
```

This comprehensive documentation covers ALL data requirements across the entire Portfolio Risk Dashboard frontend application.