# Frontend Data Requirements Specification

**Phase 1.5 Deliverable - Portfolio Risk Dashboard Integration Project**

**Document Version:** 1.0  
**Generated:** January 24, 2025  
**Analyst:** AI Frontend Requirements Analyst  
**Source:** `/frontend/src/components/layouts/RiskAnalysisDashboard.jsx` (1,836 lines)

---

## EXECUTIVE SUMMARY

This document provides a comprehensive analysis of ALL data requirements for the RiskAnalysisDashboard frontend components. Through systematic analysis of the 1,836-line React component, we have extracted every data field, data type, and usage pattern across 6 dashboard views.

**Key Findings:**
- **3 Primary Mock Data Sources** requiring backend integration
- **6 Dashboard Views** with specific data structure requirements
- **Critical Data Gaps** where components use `Math.random()` instead of real data
- **Complex Visualizations** requiring precise data formatting

**Purpose:** Enable Phase 2 adapter designers to create exact data transformation specifications.

---

## MOCK DATA STRUCTURES IDENTIFIED

### 1. `mockPortfolioData` (Lines 5-28)
**Primary portfolio information used across multiple views**

```javascript
{
  summary: {
    totalValue: 558930.33,           // Number - Portfolio total value
    riskScore: 87.5,                 // Number - Overall risk score (0-100)
    volatilityAnnual: 18.5,          // Number - Annual volatility percentage
    lastUpdated: "Jul 22, 2025, 9:12 PM"  // String - Formatted timestamp
  },
  holdings: [                        // Array - Individual position data
    {
      ticker: "SGOV",                // String - Stock ticker symbol
      name: "Cash Proxy",            // String - Security name
      value: 8365.13,                // Number - Position value in currency
      shares: 8365.13,               // Number - Number of shares held
      isProxy: true                  // Boolean - Indicates cash proxy (optional)
    }
    // ... 13 more holdings with same structure
  ]
}
```

**Usage Locations:**
- Portfolio header summary bar (lines 224-233)
- Holdings table (lines 1779-1798)
- Weight calculations across all views
- Position analysis table in FactorAnalysisView

### 2. `mockFactorData` (Lines 30-45)
**Factor analysis and risk contribution data**

```javascript
{
  factorExposures: {                 // Object - Factor beta exposures
    market: { 
      beta: 0.85,                    // Number - Factor beta value
      limit: 1.2,                    // Number - Risk limit threshold
      status: 'PASS'                 // String - "PASS" | "FAIL"
    },
    momentum: { beta: 0.42, limit: 0.5, status: 'PASS' },
    value: { beta: -0.15, limit: 0.3, status: 'PASS' },
    industry: { beta: 0.68, limit: 0.8, status: 'PASS' }
  },
  riskContributions: [               // Array - Individual position risk contributions
    {
      ticker: "MSCI",                // String - Stock ticker
      contribution: 28.5,            // Number - Risk contribution percentage
      weight: 20.8                   // Number - Portfolio weight percentage
    }
    // ... 5 more positions (DSU, IT, NVDA, Others)
  ]
}
```

**Usage Locations:**
- Factor exposure validation in FactorAnalysisView
- Risk contribution charts and tables
- Beta limit checks and compliance status

### 3. `mockPerformanceData` (Lines 47-109)
**Performance analytics and benchmark comparison data**

```javascript
{
  period: {                          // Object - Analysis time period
    start: '2019-01-31',             // String - Start date (YYYY-MM-DD)
    end: '2025-06-27',               // String - End date (YYYY-MM-DD)
    totalMonths: 61,                 // Number - Total months in period
    years: 5.08                      // Number - Years in period
  },
  returns: {                         // Object - Return metrics
    totalReturn: 222.07,             // Number - Total return percentage
    annualizedReturn: 25.87,         // Number - Annualized return percentage
    bestMonth: 17.75,                // Number - Best monthly return
    worstMonth: -10.33,              // Number - Worst monthly return
    winRate: 63.9                    // Number - Percentage of positive periods
  },
  risk: {                           // Object - Risk metrics
    volatility: 20.04,               // Number - Portfolio volatility
    maxDrawdown: -22.62,             // Number - Maximum drawdown
    downsideDeviation: 17.59,        // Number - Downside deviation
    trackingError: 8.66              // Number - Tracking error vs benchmark
  },
  riskAdjusted: {                   // Object - Risk-adjusted metrics
    sharpeRatio: 1.158,              // Number - Sharpe ratio
    sortinoRatio: 1.320,             // Number - Sortino ratio
    informationRatio: 1.273,         // Number - Information ratio
    calmarRatio: 1.144               // Number - Calmar ratio
  },
  benchmark: {                      // Object - Benchmark comparison
    name: 'SPY',                     // String - Benchmark name
    alpha: 8.48,                     // Number - Alpha vs benchmark
    beta: 1.118,                     // Number - Beta vs benchmark
    rSquared: 0.822,                 // Number - R-squared vs benchmark
    excessReturn: 11.03,             // Number - Excess return vs benchmark
    portfolioReturn: 25.87,          // Number - Portfolio return
    benchmarkReturn: 14.84,          // Number - Benchmark return
    portfolioVolatility: 20.04,      // Number - Portfolio volatility
    benchmarkVolatility: 16.26,      // Number - Benchmark volatility
    portfolioSharpe: 1.158,          // Number - Portfolio Sharpe ratio
    benchmarkSharpe: 0.749           // Number - Benchmark Sharpe ratio
  },
  monthly: {                        // Object - Monthly statistics
    avgMonthlyReturn: 2.10,          // Number - Average monthly return
    averageWin: 5.60,                // Number - Average winning month
    averageLoss: -4.11,              // Number - Average losing month
    winLossRatio: 1.36,              // Number - Win/loss ratio
    positiveMonths: 39,              // Number - Count of positive months
    negativeMonths: 22               // Number - Count of negative months
  },
  riskFreeRate: 2.65,               // Number - Risk-free rate used
  timeline: [                       // Array - Performance time series
    {
      date: 'Jan 2019',              // String - Time period label
      portfolio: 100,                // Number - Portfolio value (indexed)
      benchmark: 100                 // Number - Benchmark value (indexed)
    }
    // ... 11 more time periods (Jan 2019 to Jun 2025)
  ]
}
```

**Usage Locations:**
- PerformanceAnalyticsView: All sections use this data extensively
- Timeline charts for performance visualization
- Benchmark comparison tables and metrics

---

## VIEW-BY-VIEW DATA REQUIREMENTS

### 1. RiskScoreView (Lines 340-420)

#### Expected Data Structure:
```javascript
const componentData = [             // Array - Risk component breakdown
  {
    name: 'Concentration Risk',      // String - Component name
    score: 75,                       // Number - Component score (0-100)
    color: '#F59E0B',                // String - Hex color for visualization
    maxScore: 100                    // Number - Maximum possible score
  },
  {
    name: 'Factor Risk',
    score: 100,
    color: '#10B981',
    maxScore: 100
  },
  {
    name: 'Sector Risk',
    score: 100,
    color: '#10B981',
    maxScore: 100
  },
  {
    name: 'Volatility Risk',
    score: 75,
    color: '#F59E0B',
    maxScore: 100
  }
];
```

#### Data Sources Required:
- **Overall Risk Score**: From `mockPortfolioData.summary.riskScore` (87.5)
- **Component Scores**: Currently hardcoded, needs calculation from backend
- **Color Coding**: Based on score thresholds (Green >90, Yellow 70-90, Red <70)

#### Usage Pattern:
- Large circular score display with color-coded background
- Progress bars using `score/maxScore` percentage calculations
- Risk interpretation text based on overall score ranges
- Component breakdown with individual progress indicators

---

### 2. FactorAnalysisView (Lines 422-1019)

**Most complex view with 8 distinct data sections:**

#### A. Portfolio Risk Metrics Section (Lines 428-447)
```javascript
// Currently hardcoded - needs API integration:
{
  portfolioValue: 58900,             // Number - From mockPortfolioData.summary.totalValue
  annualVolatility: 20.11,           // Number - Percentage
  leverage: 1.28,                    // Number - Leverage multiplier
  factorVariance: 62,                // Number - Factor variance percentage
  idiosyncraticVariance: 38          // Number - Specific variance percentage (100 - factorVariance)
}
```

#### B. Variance Decomposition Chart (Lines 450-510)
```javascript
const varianceDecomposition = {
  factorRisk: {
    percentage: 62,                  // Number - Factor risk percentage
    breakdown: {
      market: 54,                    // Number - Market factor percentage
      value: 6,                      // Number - Value factor percentage  
      momentum: 2                    // Number - Momentum factor percentage
    }
  },
  idiosyncraticRisk: 38              // Number - Idiosyncratic risk percentage
};
```

#### C. Risk Limit Checks (Lines 517-613)
```javascript
const riskLimitChecks = [
  {
    metric: "Factor Variance %",      // String - Metric name
    current: 61.51,                  // Number - Current value
    limit: 30.00,                    // Number - Threshold limit
    status: "FAIL",                  // String - "PASS" | "FAIL"
    utilization: 205.0,              // Number - current/limit * 100
    position: "calc(100% * 61.51 / 126)"  // String - CSS position for dot gauge
  },
  {
    metric: "Market Variance %",
    current: 53.95,
    limit: 50.00,
    status: "FAIL",
    utilization: 107.9,
    position: "calc(100% * 53.95 / 54)"
  },
  {
    metric: "Market β",
    current: 1.18,
    limit: 0.77,
    status: "FAIL",
    utilization: 153.2,
    position: "calc(100% * 1.18 / 1.18)"
  },
  {
    metric: "Momentum β",
    current: -0.33,
    limit: 0.79,
    status: "PASS",
    utilization: 41.8,
    position: "calc(100% * 0.33 / 0.79)"
  },
  {
    metric: "Value β",
    current: 0.13,
    limit: 0.55,
    status: "PASS",
    utilization: 23.6,
    position: "calc(100% * 0.13 / 0.55)"
  },
  {
    metric: "Portfolio Volatility",
    current: 20.11,
    limit: 40.00,
    status: "PASS",
    utilization: 50.3,
    position: "calc(100% * 20.11 / 40)"
  }
];
```

#### D. Industry Variance Contributions (Lines 619-684)
```javascript
const industryVariance = [
  {
    industry: "REM (REIT - Mortgage)", // String - Industry description
    variance: 30.2,                   // Number - Variance contribution percentage
    color: "purple-500"               // String - Tailwind color class
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
  },
  {
    industry: "XLK (Consumer Electronics)",
    variance: 7.8,
    color: "orange-500"
  },
  {
    industry: "SOXX (Semiconductors)",
    variance: 5.4,
    color: "yellow-500"
  },
  {
    industry: "SLV (Silver)",
    variance: 2.3,
    color: "pink-500"
  },
  {
    industry: "XOP (Oil & Gas E&P)",
    variance: 2.2,
    color: "red-500"
  },
  {
    industry: "KIE (Insurance)",
    variance: 0.7,
    color: "indigo-500"
  },
  {
    industry: "XLC (Media & Entertainment)",
    variance: 0.3,
    color: "teal-500"
  }
];
```

#### E. Risk Contributions Pareto Chart (Lines 833-843)
```javascript
const riskContributionsChart = [
  {
    ticker: "MSCI",                  // String - Stock ticker
    contribution: 23.7,              // Number - Individual risk contribution
    cumulative: 23.7                 // Number - Cumulative risk for Pareto line
  },
  {
    ticker: "STWD",
    contribution: 20.2,
    cumulative: 43.9                 // Running total: 23.7 + 20.2
  },
  {
    ticker: "IT",
    contribution: 17.6,
    cumulative: 61.5                 // Running total: 43.9 + 17.6
  },
  {
    ticker: "DSU",
    contribution: 11.8,
    cumulative: 73.3
  },
  {
    ticker: "NVDA",
    contribution: 10.4,
    cumulative: 83.7
  },
  {
    ticker: "KINS",
    contribution: 3.7,
    cumulative: 87.4
  },
  {
    ticker: "SFM",
    contribution: 2.5,
    cumulative: 89.9
  },
  {
    ticker: "Others",
    contribution: 10.1,
    cumulative: 100.0
  }
];
```

#### F. Position Analysis Table (Lines 894-911)
```javascript
// ⚠️ CRITICAL: Currently uses Math.random() - NEEDS REAL API DATA
const positionAnalysisData = mockPortfolioData.holdings.map(holding => ({
  ticker: holding.ticker,            // String - From holdings data
  weight: (holding.value / mockPortfolioData.summary.totalValue) * 100,  // Number - Calculated percentage
  riskContribution: Math.random() * 20 + 5,    // ❌ MOCK DATA - NEEDS REAL VALUE
  marketBeta: Math.random() * 0.8 + 0.6,       // ❌ MOCK DATA - NEEDS REAL VALUE  
  momentumBeta: Math.random() * 0.4 - 0.2,     // ❌ MOCK DATA - NEEDS REAL VALUE
  valueBeta: Math.random() * 0.4 - 0.2,        // ❌ MOCK DATA - NEEDS REAL VALUE
  industryBeta: Math.random() * 0.8 + 0.6,     // ❌ MOCK DATA - NEEDS REAL VALUE
  subindustryBeta: Math.random() * 0.8 + 0.6   // ❌ MOCK DATA - NEEDS REAL VALUE
}));
```

#### G. Correlation Matrix Heatmap (Lines 932-991)
```javascript
// ⚠️ CRITICAL: Hardcoded correlation matrix - NEEDS REAL API DATA
const correlationMatrix = [
  // Triangular matrix structure (null for upper triangle)
  ['DSU', [1.00, 0.20, 0.12, 0.59, 0.06, 0.60, 0.50, 0.04, 0.28, 0.08, 0.13, 0.67, 0.31, 0.48]],
  ['EQT', [null, 1.00, -0.23, 0.01, 0.02, -0.03, 0.08, 0.05, 0.20, 0.02, 0.12, 0.17, 0.35, 0.12]],
  ['IGIC', [null, null, 1.00, 0.30, 0.40, 0.32, 0.08, 0.04, 0.22, 0.06, 0.03, 0.26, -0.05, 0.18]],
  ['IT', [null, null, null, 1.00, 0.04, 0.55, 0.33, -0.04, 0.26, 0.12, 0.09, 0.53, -0.01, 0.43]],
  ['KINS', [null, null, null, null, 1.00, 0.11, 0.03, 0.06, 0.21, 0.23, 0.02, 0.11, 0.06, 0.24]],
  ['MSCI', [null, null, null, null, null, 1.00, 0.50, 0.03, 0.14, 0.09, 0.21, 0.62, 0.23, 0.51]],
  ['NVDA', [null, null, null, null, null, null, 1.00, 0.03, 0.20, 0.16, 0.19, 0.37, 0.14, 0.27]],
  ['RNMBY', [null, null, null, null, null, null, null, 1.00, 0.25, 0.17, 0.21, 0.13, 0.30, 0.28]],
  ['SFM', [null, null, null, null, null, null, null, null, 1.00, 0.21, 0.11, 0.17, 0.22, 0.17]],
  ['SGOV', [null, null, null, null, null, null, null, null, null, 1.00, 0.09, 0.07, 0.16, 0.18]],
  ['SLV', [null, null, null, null, null, null, null, null, null, null, 1.00, 0.03, 0.19, 0.14]],
  ['STWD', [null, null, null, null, null, null, null, null, null, null, null, 1.00, 0.29, 0.67]],
  ['TKO', [null, null, null, null, null, null, null, null, null, null, null, null, 1.00, 0.22]],
  ['V', [null, null, null, null, null, null, null, null, null, null, null, null, null, 1.00]]
];
```

#### H. Beta Exposure Checks (Lines 694-825)
```javascript
const betaExposureChecks = {
  mainFactors: [                     // Array - Primary factor betas
    {
      factor: "Market β",            // String - Factor name
      beta: 1.18,                    // Number - Current beta value
      limit: 0.77,                   // Number - Limit threshold
      status: "FAIL"                 // String - "PASS" | "FAIL"
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
  industryProxyBetas: [              // Array - Industry proxy betas
    {
      proxy: "DSU",                  // String - Industry proxy ticker
      beta: 0.25,                    // Number - Beta value
      limit: 0.50,                   // Number - Limit threshold
      status: "PASS"                 // String - "PASS" | "FAIL"
    },
    {
      proxy: "REM",
      beta: 0.18,
      limit: 0.18,
      status: "PASS"
    },
    {
      proxy: "KCE",
      beta: 0.16,
      limit: 0.56,
      status: "PASS"
    },
    {
      proxy: "XLK",
      beta: 0.14,
      limit: 0.82,
      status: "PASS"
    },
    {
      proxy: "SOXX",
      beta: 0.09,
      limit: 0.56,
      status: "PASS"
    },
    {
      proxy: "KIE",
      beta: 0.06,
      limit: 0.47,
      status: "PASS"
    },
    {
      proxy: "SLV",
      beta: 0.06,
      limit: 0.57,
      status: "PASS"
    },
    {
      proxy: "XOP",
      beta: 0.03,
      limit: 0.21,
      status: "PASS"
    },
    {
      proxy: "XLP",
      beta: 0.03,
      limit: 1.03,
      status: "PASS"
    },
    {
      proxy: "XLC",
      beta: 0.03,
      limit: 0.71,
      status: "PASS"
    },
    {
      proxy: "ITA",
      beta: 0.02,
      limit: 0.35,
      status: "PASS"
    },
    {
      proxy: "SGOV",
      beta: -0.14,
      limit: 21.90,
      status: "PASS"
    }
  ]
};
```

#### I. Treemap Variance Visualization (Lines 1024-1140)
```javascript
const treemapVarianceData = [
  {
    ticker: "MSCI",                  // String - Stock ticker
    industry: "Technology",          // String - Industry classification
    variance: 23.7,                  // Number - Variance contribution percentage
    position: {                      // Object - Rectangle positioning for treemap
      left: '0%',                    // String - CSS left position
      top: '0%',                     // String - CSS top position
      width: '35%',                  // String - CSS width
      height: '60%'                  // String - CSS height
    },
    color: "blue-600",               // String - Tailwind color class
    textColor: "text-white"          // String - Text color class
  },
  {
    ticker: "STWD",
    industry: "REIT",
    variance: 20.2,
    position: {
      left: '37%',
      top: '0%',
      width: '30%',
      height: '60%'
    },
    color: "purple-600",
    textColor: "text-white"
  },
  {
    ticker: "IT",
    industry: "Technology",
    variance: 17.6,
    position: {
      left: '69%',
      top: '0%',
      width: '31%',
      height: '42%'
    },
    color: "blue-500",
    textColor: "text-white"
  },
  {
    ticker: "DSU",
    industry: "Energy",
    variance: 11.8,
    position: {
      left: '0%',
      top: '62%',
      width: '25%',
      height: '38%'
    },
    color: "green-600",
    textColor: "text-white"
  },
  {
    ticker: "NVDA",
    industry: "Technology",
    variance: 10.4,
    position: {
      left: '27%',
      top: '62%',
      width: '22%',
      height: '38%'
    },
    color: "blue-400",
    textColor: "text-white"
  },
  {
    ticker: "V",
    industry: "Financial",
    variance: 6.7,
    position: {
      left: '69%',
      top: '44%',
      width: '31%',
      height: '25%'
    },
    color: "orange-500",
    textColor: "text-white"
  },
  {
    ticker: "Others",
    industry: "Mixed",
    variance: 9.6,
    position: {
      left: '51%',
      top: '62%',
      width: '49%',
      height: '31%'
    },
    color: "gray-500",
    textColor: "text-white"
  }
];
```

---

### 3. PerformanceAnalyticsView (Lines 1142-1359)

**Uses `mockPerformanceData` extensively across all sections:**

#### Required Data Mapping:
```javascript
// All sections require fields from mockPerformanceData:

// A. Analysis Period Header (Lines 1146-1152)
period: {
  start: mockPerformanceData.period.start,           // String: '2019-01-31'
  end: mockPerformanceData.period.end,               // String: '2025-06-27'
  totalMonths: mockPerformanceData.period.totalMonths, // Number: 61
  years: mockPerformanceData.period.years            // Number: 5.08
}

// B. Return Metrics Grid (Lines 1157-1178)
returns: {
  totalReturn: mockPerformanceData.returns.totalReturn,         // Number: 222.07
  annualizedReturn: mockPerformanceData.returns.annualizedReturn, // Number: 25.87
  bestMonth: mockPerformanceData.returns.bestMonth,             // Number: 17.75
  worstMonth: mockPerformanceData.returns.worstMonth,           // Number: -10.33
  winRate: mockPerformanceData.returns.winRate                  // Number: 63.9
}

// C. Performance Timeline Chart (Lines 1183-1195)
timeline: mockPerformanceData.timeline,              // Array of objects with date, portfolio, benchmark

// D. Risk Metrics Grid (Lines 1221-1240)
risk: {
  volatility: mockPerformanceData.risk.volatility,             // Number: 20.04
  maxDrawdown: mockPerformanceData.risk.maxDrawdown,           // Number: -22.62
  downsideDeviation: mockPerformanceData.risk.downsideDeviation, // Number: 17.59
  trackingError: mockPerformanceData.risk.trackingError        // Number: 8.66
}

// E. Risk-Adjusted Returns Grid (Lines 1244-1263)
riskAdjusted: {
  sharpeRatio: mockPerformanceData.riskAdjusted.sharpeRatio,         // Number: 1.158
  sortinoRatio: mockPerformanceData.riskAdjusted.sortinoRatio,       // Number: 1.320
  informationRatio: mockPerformanceData.riskAdjusted.informationRatio, // Number: 1.273
  calmarRatio: mockPerformanceData.riskAdjusted.calmarRatio          // Number: 1.144
}

// F. Benchmark Analysis Section (Lines 1266-1325)
benchmark: {
  name: mockPerformanceData.benchmark.name,                    // String: 'SPY'
  alpha: mockPerformanceData.benchmark.alpha,                  // Number: 8.48
  beta: mockPerformanceData.benchmark.beta,                    // Number: 1.118
  rSquared: mockPerformanceData.benchmark.rSquared,            // Number: 0.822
  excessReturn: mockPerformanceData.benchmark.excessReturn,    // Number: 11.03
  portfolioReturn: mockPerformanceData.benchmark.portfolioReturn,    // Number: 25.87
  benchmarkReturn: mockPerformanceData.benchmark.benchmarkReturn,    // Number: 14.84
  portfolioVolatility: mockPerformanceData.benchmark.portfolioVolatility,  // Number: 20.04
  benchmarkVolatility: mockPerformanceData.benchmark.benchmarkVolatility,  // Number: 16.26
  portfolioSharpe: mockPerformanceData.benchmark.portfolioSharpe,    // Number: 1.158
  benchmarkSharpe: mockPerformanceData.benchmark.benchmarkSharpe     // Number: 0.749
}

// G. Monthly Statistics Grid (Lines 1328-1356)
monthly: {
  avgMonthlyReturn: mockPerformanceData.monthly.avgMonthlyReturn,   // Number: 2.10
  averageWin: mockPerformanceData.monthly.averageWin,              // Number: 5.60
  averageLoss: mockPerformanceData.monthly.averageLoss,            // Number: -4.11
  winLossRatio: mockPerformanceData.monthly.winLossRatio,          // Number: 1.36
  positiveMonths: mockPerformanceData.monthly.positiveMonths,      // Number: 39
  negativeMonths: mockPerformanceData.monthly.negativeMonths       // Number: 22
}
```

#### Chart Requirements:
- **Line Chart**: Uses `timeline` array with `date`, `portfolio`, `benchmark` fields
- **Chart Colors**: Uses `CHART_COLORS.primary` (#3B82F6) and `CHART_COLORS.gray` (#6B7280)
- **Tooltip Formatting**: Custom formatters for percentage display

---

### 4. AnalysisReportView (Lines 1361-1487)

**Static report format with embedded metric values:**

#### Required Data Sources:
```javascript
const reportData = {
  // Report metadata
  generatedDate: new Date().toLocaleDateString(),    // String - Current date
  
  // Executive summary metrics (currently hardcoded)
  riskScore: 87.5,                   // Number - From mockPortfolioData.summary.riskScore
  volatilityAnnual: 18.5,            // Number - From mockPortfolioData.summary.volatilityAnnual
  
  // Risk assessment metrics (currently hardcoded - needs calculation)
  portfolioMetrics: {
    volatility: 18.5,                // Number - Annual volatility
    sharpeRatio: 1.24,               // Number - Sharpe ratio
    maxDrawdown: -8.4,               // Number - Maximum drawdown
    valueAtRisk: -12.3               // Number - VaR (95%)
  },
  
  // Risk component scores (currently hardcoded - needs calculation)
  riskComponents: {
    concentrationRisk: 75,           // Number - Concentration component score (0-100)
    factorRisk: 100,                 // Number - Factor component score (0-100)
    sectorRisk: 100,                 // Number - Sector component score (0-100)
    volatilityRisk: 75               // Number - Volatility component score (0-100)
  },
  
  // Recommendation data (currently static text - could be dynamic)
  recommendations: [
    {
      category: "Concentration Risk Management",
      description: "Consider reducing position sizes in MSCI (20.8%) and DSU (26.7%) to improve diversification.",
      type: "warning"              // String - "warning" | "info" | "success"
    },
    {
      category: "Volatility Optimization", 
      description: "Adding low-volatility assets or defensive positions could reduce overall portfolio volatility.",
      type: "info"
    },
    {
      category: "Factor Exposure",
      description: "Excellent factor diversification. Current exposures are within acceptable limits.",
      type: "success"
    }
  ]
};
```

#### Export Functionality:
- **PDF Export**: Button for PDF generation (not implemented)
- **CSV Export**: Button for CSV data export (not implemented)  
- **Share Report**: Button for report sharing (not implemented)

---

### 5. RiskSettingsView (Lines 1489-1739)

**Configuration interface with settings state management:**

#### Settings Data Structure:
```javascript
const riskSettings = {
  // Portfolio Limits
  maxVolatility: 40,                 // Number - Percentage (0.4 as 40)
  maxLoss: -25,                      // Number - Percentage (-0.25 as -25)
  
  // Concentration Limits  
  maxSingleStockWeight: 40,          // Number - Percentage (0.4 as 40)
  
  // Variance Limits
  maxFactorContribution: 30,         // Number - Percentage (0.3 as 30)
  maxMarketContribution: 50,         // Number - Percentage (0.5 as 50)
  maxIndustryContribution: 30,       // Number - Percentage (0.3 as 30)
  
  // Single Factor Loss
  maxSingleFactorLoss: -10           // Number - Percentage (-0.1 as -10)
};
```

#### Compliance Status Data:
```javascript
const complianceStatus = [
  {
    type: "VIOLATION",               // String - "VIOLATION" | "WARNING" | "PASS"
    metric: "Maximum Loss Limit",    // String - Metric name
    description: "Current drawdown (-22.62%) exceeds limit (-25%)",  // String - Description
    current: -22.62,                 // Number - Current value
    limit: -25,                      // Number - Limit threshold
    colorClass: "bg-red-50 border-red-200"  // String - Tailwind classes
  },
  {
    type: "WARNING",
    metric: "Single Stock Weight",
    description: "DSU (26.7%) approaching limit (40%)",
    current: 26.7,
    limit: 40,
    colorClass: "bg-yellow-50 border-yellow-200"
  },
  {
    type: "PASS",
    metric: "Portfolio Volatility",
    description: "Current volatility (20.04%) within limit (40%)",
    current: 20.04,
    limit: 40,
    colorClass: "bg-green-50 border-green-200"
  },
  {
    type: "PASS", 
    metric: "Factor Contributions",
    description: "All factor contributions within limits",
    current: null,                   // Number - Not applicable for aggregate check
    limit: null,
    colorClass: "bg-green-50 border-green-200"
  },
  {
    type: "PASS",
    metric: "Single Factor Loss", 
    description: "Worst scenario (-8.2%) within limit (-10%)",
    current: -8.2,
    limit: -10,
    colorClass: "bg-green-50 border-green-200"
  }
];
```

#### Recommended Limits Data:
```javascript
const recommendedLimits = [
  {
    setting: "Position Size Limit",   // String - Setting name
    suggested: 31.2,                 // Number - Suggested value
    current: 25.3,                   // Number - Current value
    description: "Recommended maximum for single positions"  // String - Description
  },
  {
    setting: "Portfolio Volatility Limit",
    suggested: 25.0,
    current: 20.0,
    description: "Maximum acceptable portfolio volatility"
  },
  {
    setting: "Sector Concentration Limit",
    suggested: 50.0,
    current: 0.0,
    description: "Maximum exposure to any single sector"
  }
];
```

#### Form Interaction:
- **Input Handling**: `handleSettingChange(key, value)` function
- **Validation**: Input field validation (not implemented)
- **Save/Reset**: Action buttons for settings persistence

---

### 6. HoldingsView (Lines 1741-1834)

**Portfolio holdings table and account connections:**

#### Holdings Table Data:
```javascript
// Uses mockPortfolioData.holdings directly with calculated fields:
const holdingsTableData = mockPortfolioData.holdings.map(holding => ({
  ticker: holding.ticker,            // String - Stock symbol
  name: holding.name,                // String - Security name
  shares: holding.shares,            // Number - Share count
  value: holding.value,              // Number - Market value
  weight: (holding.value / mockPortfolioData.summary.totalValue) * 100,  // Number - Calculated weight percentage
  isProxy: holding.isProxy           // Boolean - Cash proxy flag (optional field)
}));
```

#### Portfolio Summary:
```javascript
const portfolioSummary = {
  totalValue: mockPortfolioData.summary.totalValue,      // Number - Total portfolio value
  lastUpdated: mockPortfolioData.summary.lastUpdated     // String - Last update timestamp
};
```

#### Connected Accounts Data:
```javascript
// Currently hardcoded placeholder - needs Plaid/broker integration:
const connectedAccounts = [
  {
    name: "Interactive Brokers",     // String - Brokerage name
    lastSynced: "2 hours ago",       // String - Last sync timestamp
    status: "Active",                // String - Connection status
    statusColor: "bg-green-100 text-green-800"  // String - Status badge colors
  },
  {
    name: "Merrill Lynch",
    lastSynced: "1 day ago", 
    status: "Active",
    statusColor: "bg-green-100 text-green-800"
  }
];
```

#### Action Buttons:
- **Refresh**: Portfolio data refresh trigger
- **Analyze Risk**: Risk analysis workflow trigger  
- **Connect Account**: New brokerage account connection

---

## UI-SPECIFIC DATA REQUIREMENTS

### Color Constants and Themes

#### Chart Color Palette (Lines 112-118):
```javascript
const CHART_COLORS = {
  primary: '#3B82F6',      // Blue - main charts and primary elements
  success: '#10B981',      // Green - positive values, success states
  warning: '#F59E0B',      // Orange/Yellow - warnings, moderate risk
  danger: '#EF4444',       // Red - violations, high risk, alerts
  gray: '#6B7280'          // Gray - neutral elements, secondary data
};
```

#### Status Color Mapping:
```javascript
const statusColors = {
  PASS: {
    background: 'bg-green-100',      // Light green background
    text: 'text-green-800',          // Dark green text
    badge: 'bg-green-500'            // Solid green for indicators
  },
  FAIL: {
    background: 'bg-red-100',
    text: 'text-red-800', 
    badge: 'bg-red-500'
  },
  WARNING: {
    background: 'bg-yellow-100',
    text: 'text-yellow-800',
    badge: 'bg-yellow-500'
  },
  VIOLATION: {
    background: 'bg-red-100',
    text: 'text-red-800',
    badge: 'bg-red-500'
  }
};
```

#### Industry Color Mapping:
```javascript
const industryColors = {
  "Technology": "blue-500",          // Blue shades for tech
  "REIT": "purple-600",              // Purple for real estate
  "Energy": "green-600",             // Green for energy
  "Financial": "orange-500",         // Orange for financial services
  "Mixed": "gray-500",               // Gray for diversified/other
  "Default": "gray-400"              // Default fallback color
};
```

### Chart-Specific Requirements

#### 1. Bar Charts (Recharts):
```javascript
// Required data structure for BarChart component:
const barChartData = [
  {
    [xAxisKey]: "string",            // X-axis category (e.g., "MSCI")
    [dataKey]: number,               // Y-axis value (e.g., 23.7)
    [additionalKeys]: any            // Optional additional data fields
  }
];

// Configuration requirements:
{
  margin: { top: 20, right: 90, left: 60, bottom: 5 },
  dataKey: "contribution",           // Primary data field
  fill: CHART_COLORS.primary        // Color from constants
}
```

#### 2. Line Charts (Recharts):
```javascript
// Required data structure for LineChart component:
const lineChartData = [
  {
    date: "string",                  // X-axis (e.g., "Jan 2019")
    portfolio: number,               // First line data
    benchmark: number                // Second line data
  }
];

// Multiple line configuration:
{
  Line1: { dataKey: "portfolio", stroke: CHART_COLORS.primary },
  Line2: { dataKey: "benchmark", stroke: CHART_COLORS.gray }
}
```

#### 3. Correlation Matrix Heatmap:
```javascript
// Special triangular matrix structure:
const correlationData = [
  [ticker1, [1.00, corr12, corr13, ...]],      // Full row
  [ticker2, [null, 1.00, corr23, ...]],        // null for upper triangle
  [ticker3, [null, null, 1.00, ...]]           // Triangular structure
];

// Color calculation for heatmap:
const getHeatmapColor = (correlation) => {
  if (correlation === 1.00) return 'rgb(75, 85, 99)';  // Dark gray diagonal
  if (correlation > 0) {
    const intensity = Math.round(Math.abs(correlation) * 120);
    return `rgb(${255-intensity}, ${255-intensity*0.9}, ${255-intensity*0.8})`;  // Warm colors
  } else {
    const intensity = Math.round(Math.abs(correlation) * 120); 
    return `rgb(${255-intensity*0.8}, ${255-intensity*0.9}, ${255-intensity})`;  // Cool colors
  }
};
```

#### 4. Treemap Positioning:
```javascript
// Calculated rectangle positions for treemap visualization:
const calculateTreemapPositions = (data) => {
  // Algorithm needed to convert variance percentages to CSS positions
  return data.map(item => ({
    ...item,
    position: {
      left: `${calculatedLeft}%`,    // CSS percentage string
      top: `${calculatedTop}%`,      // CSS percentage string  
      width: `${calculatedWidth}%`,  // CSS percentage string
      height: `${calculatedHeight}%` // CSS percentage string
    }
  }));
};
```

#### 5. Gauge/Dot Plot Charts:
```javascript
// CSS position calculation for gauge indicators:
const calculateGaugePosition = (current, limit, maxValue) => {
  const percentage = (current / maxValue) * 100;
  return `calc(100% * ${current} / ${maxValue})`;  // CSS calc() expression
};

// Status determination:
const getGaugeStatus = (current, limit) => {
  return Math.abs(current) > Math.abs(limit) ? "FAIL" : "PASS";
};
```

---

## CALCULATED FIELDS AND TRANSFORMATIONS

### Frontend Calculation Requirements

#### 1. Weight Percentage Calculations:
```javascript
// Portfolio weight calculation (used throughout views):
const calculateWeight = (holdingValue, totalPortfolioValue) => {
  return (holdingValue / totalPortfolioValue) * 100;  // Returns percentage
};

// Usage locations:
// - HoldingsView table
// - FactorAnalysisView position table  
// - Weight displays across all views
```

#### 2. Cumulative Risk Calculations:
```javascript
// Pareto chart cumulative calculation:
const calculateCumulativeRisk = (riskContributions) => {
  let cumulative = 0;
  return riskContributions.map(item => {
    cumulative += item.contribution;
    return { ...item, cumulative };
  });
};
```

#### 3. Status Derivation:
```javascript
// Limit check status calculation:
const deriveStatus = (current, limit) => {
  if (typeof current === 'number' && typeof limit === 'number') {
    return Math.abs(current) > Math.abs(limit) ? "FAIL" : "PASS";
  }
  return "UNKNOWN";
};

// Compliance level calculation:
const getComplianceLevel = (current, limit) => {
  const utilization = Math.abs(current / limit) * 100;
  if (utilization > 100) return "VIOLATION";
  if (utilization > 80) return "WARNING"; 
  return "PASS";
};
```

#### 4. CSS Position Calculations:
```javascript
// Gauge dot positioning:
const calculateDotPosition = (value, min, max) => {
  const percentage = ((value - min) / (max - min)) * 100;
  return `calc(${percentage}% - 6px)`;  // Offset for dot center
};

// Progress bar width:
const calculateProgressWidth = (current, maximum) => {
  return `${Math.min((current / maximum) * 100, 100)}%`;
};
```

### Data Transformation Requirements

#### 1. Backend to Frontend Mapping:
```javascript
// Expected transformation patterns:
const transformBackendData = (apiResponse) => {
  return {
    // Decimal to percentage conversion:
    volatility: apiResponse.volatility * 100,           // 0.185 → 18.5
    
    // Date formatting:
    lastUpdated: formatDate(apiResponse.last_updated),  // ISO → "Jul 22, 2025, 9:12 PM"
    
    // Status string conversion:
    status: apiResponse.is_within_limit ? "PASS" : "FAIL",
    
    // Color assignment:
    color: getColorForValue(apiResponse.risk_score),
    
    // Nested object flattening:
    portfolioReturn: apiResponse.performance.portfolio.return,
    benchmarkReturn: apiResponse.performance.benchmark.return
  };
};
```

#### 2. Required Utility Functions:
```javascript
// Date formatting utility:
const formatDisplayDate = (isoString) => {
  return new Date(isoString).toLocaleString();  // "Jul 22, 2025, 9:12 PM"
};

// Number formatting utility:
const formatPercentage = (decimal, precision = 1) => {
  return (decimal * 100).toFixed(precision);    // 0.185 → "18.5"
};

// Currency formatting utility:
const formatCurrency = (value) => {
  return value.toLocaleString('en-US', {        // 558930.33 → "558,930"
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0
  });
};
```

---

## CRITICAL DATA GAPS IDENTIFIED

### ⚠️ Fields Currently Using Mock/Random Data

#### 1. Factor Analysis Position Table (Lines 894-911):
```javascript
// ❌ URGENT: These fields use Math.random() and need real API data:
{
  riskContribution: Math.random() * 20 + 5,      // Need: actual risk contribution %
  marketBeta: Math.random() * 0.8 + 0.6,         // Need: actual market beta
  momentumBeta: Math.random() * 0.4 - 0.2,       // Need: actual momentum beta  
  valueBeta: Math.random() * 0.4 - 0.2,          // Need: actual value beta
  industryBeta: Math.random() * 0.8 + 0.6,       // Need: actual industry beta
  subindustryBeta: Math.random() * 0.8 + 0.6     // Need: actual subindustry beta
}
```

#### 2. Correlation Matrix (Lines 932-991):
```javascript
// ❌ URGENT: Hardcoded correlation matrix needs real correlation calculations:
const correlationMatrix = [
  ['DSU', [1.00, 0.20, 0.12, ...]],   // Need: actual correlations from API
  ['EQT', [null, 1.00, -0.23, ...]],  // Currently static hardcoded values
  // ... all 14x14 matrix values need real data
];
```

#### 3. Risk Metrics Calculations:
```javascript
// ❌ Missing calculations that need backend implementation:
{
  factorVariance: 62,                  // Need: calculated factor variance %
  idiosyncraticVariance: 38,           // Need: calculated specific variance %
  leverage: 1.28,                      // Need: portfolio leverage calculation
  valueAtRisk: -12.3,                  // Need: VaR calculation (95% confidence)
  downsideDeviation: 17.59,            // Need: downside deviation calculation
  trackingError: 8.66                  // Need: tracking error vs benchmark
}
```

#### 4. Industry Classification:
```javascript
// ❌ Missing industry mapping:
{
  ticker: "MSCI",
  industry: "Technology",              // Need: actual industry classification
  industryCode: "TECH",                // Need: standardized industry codes
  subIndustry: "Software & Services"   // Need: sub-industry classification
}
```

### Fields Requiring Backend Calculation

#### 1. Risk Component Scores:
```javascript
// Currently hardcoded in RiskScoreView - need algorithmic calculation:
{
  concentrationRisk: 75,     // Need: concentration risk algorithm
  factorRisk: 100,          // Need: factor risk scoring
  sectorRisk: 100,          // Need: sector risk scoring  
  volatilityRisk: 75        // Need: volatility risk scoring
}
```

#### 2. Compliance Status:
```javascript
// Need real-time compliance checking:
{
  currentDrawdown: -22.62,   // Need: actual current drawdown calculation
  largestPosition: 26.7,     // Need: actual largest position weight
  factorContribution: 65,    // Need: actual factor contribution calculation
  marketContribution: 42     // Need: actual market contribution calculation
}
```

#### 3. Benchmark Comparison:
```javascript
// Need benchmark analysis calculations:
{
  alpha: 8.48,              // Need: alpha calculation vs benchmark
  beta: 1.118,              // Need: beta calculation vs benchmark  
  rSquared: 0.822,          // Need: R-squared calculation
  informationRatio: 1.273,  // Need: information ratio calculation
  trackingError: 8.66       // Need: tracking error calculation
}
```

---

## PERFORMANCE CONSIDERATIONS

### Large Dataset Handling

#### 1. Correlation Matrix:
- **Complexity**: O(n²) for n positions (currently 14x14 = 196 values)
- **Scalability**: May need optimization for portfolios with 50+ positions
- **Rendering**: Consider virtualization for large matrices

#### 2. Position Analysis Table:
- **Current Size**: 14 positions displayed
- **Scalability**: May need pagination for 100+ position portfolios
- **Filtering**: Consider adding search/filter capabilities

#### 3. Time Series Data:
- **Current Size**: 12 data points for timeline chart
- **Scalability**: Daily data for 5 years = 1,825 points
- **Optimization**: Consider data sampling for longer time periods

### Real-Time Update Requirements

#### 1. Market Data Updates:
```javascript
// Data refresh patterns needed:
{
  portfolioValues: "real-time",      // Position values update with market
  riskMetrics: "5-minute",           // Risk calculations refresh periodically  
  correlations: "daily",             // Correlation matrix updates daily
  benchmarkData: "real-time"         // Benchmark comparison updates with market
}
```

#### 2. State Management:
- **Loading States**: Each section needs independent loading indicators
- **Error Boundaries**: Chart failures should not crash entire view
- **Caching Strategy**: Expensive calculations should be cached

---

## INTEGRATION REQUIREMENTS SUMMARY

### API Endpoint Mapping Needed

#### 1. Portfolio Data:
```javascript
// Endpoint: /api/portfolio/summary
{
  totalValue: number,
  riskScore: number,
  volatilityAnnual: number,
  lastUpdated: string
}

// Endpoint: /api/portfolio/holdings  
[{
  ticker: string,
  name: string,
  value: number,
  shares: number,
  weight: number,
  isProxy?: boolean
}]
```

#### 2. Risk Analysis Data:
```javascript
// Endpoint: /api/risk/factor-analysis
{
  portfolioMetrics: { volatility, leverage, factorVariance, ... },
  factorExposures: { market: {beta, limit, status}, ... },
  riskContributions: [{ ticker, contribution, weight }],
  betaExposures: { mainFactors: [...], industryProxies: [...] },
  correlationMatrix: [[ticker, [correlations]]],
  riskLimitChecks: [{ metric, current, limit, status }],
  industryVariance: [{ industry, variance, color }]
}

// Endpoint: /api/risk/score-components
{
  overallScore: number,
  components: {
    concentrationRisk: number,
    factorRisk: number, 
    sectorRisk: number,
    volatilityRisk: number
  }
}
```

#### 3. Performance Data:
```javascript
// Endpoint: /api/performance/analytics
{
  period: { start, end, totalMonths, years },
  returns: { totalReturn, annualizedReturn, bestMonth, worstMonth, winRate },
  risk: { volatility, maxDrawdown, downsideDeviation, trackingError },
  riskAdjusted: { sharpeRatio, sortinoRatio, informationRatio, calmarRatio },
  benchmark: { name, alpha, beta, rSquared, excessReturn, ... },
  monthly: { avgMonthlyReturn, averageWin, averageLoss, winLossRatio, ... },
  timeline: [{ date, portfolio, benchmark }]
}
```

#### 4. Settings and Configuration:
```javascript
// Endpoint: /api/settings/risk-limits
{
  portfolioLimits: { maxVolatility, maxLoss },
  concentrationLimits: { maxSingleStockWeight },
  varianceLimits: { maxFactorContribution, maxMarketContribution, maxIndustryContribution },
  singleFactorLimits: { maxSingleFactorLoss }
}

// Endpoint: /api/compliance/status
[{
  type: "VIOLATION" | "WARNING" | "PASS",
  metric: string,
  description: string,
  current: number,
  limit: number
}]
```

### Data Validation Requirements

#### 1. Type Checking:
```javascript
// Required validation for all numeric fields:
const validateNumericField = (value, fieldName) => {
  if (typeof value !== 'number' || isNaN(value)) {
    throw new Error(`${fieldName} must be a valid number`);
  }
};

// Required validation for percentage fields:
const validatePercentage = (value, fieldName) => {
  if (value < -100 || value > 1000) {  // Allow for leveraged portfolios
    console.warn(`${fieldName} percentage seems out of range: ${value}%`);
  }
};
```

#### 2. Data Completeness:
```javascript
// Required fields validation:
const validatePortfolioData = (data) => {
  const required = ['totalValue', 'riskScore', 'volatilityAnnual', 'holdings'];
  required.forEach(field => {
    if (!data[field]) throw new Error(`Missing required field: ${field}`);
  });
};
```

#### 3. Fallback Values:
```javascript
// Default values for optional fields:
const applyDefaults = (data) => ({
  isProxy: false,
  color: CHART_COLORS.gray,
  status: "UNKNOWN",
  ...data
});
```

---

## DELIVERABLE COMPLETION CHECKLIST

✅ **Mock Data Extraction**: All 3 primary data structures documented with field-by-field analysis  
✅ **View Analysis**: All 6 dashboard views analyzed with exact data requirements  
✅ **Data Types**: Every field documented with data type and expected format  
✅ **Usage Patterns**: Component rendering patterns and data dependencies mapped  
✅ **UI Requirements**: Color schemes, chart configurations, and status mappings documented  
✅ **Calculated Fields**: All derived values and transformation logic identified  
✅ **Critical Gaps**: Mock/random data fields requiring real API integration identified  
✅ **Performance Considerations**: Scalability and optimization requirements documented  
✅ **Integration Specifications**: API endpoint mapping and validation requirements defined  

---

## NEXT PHASE HANDOFF REQUIREMENTS

**For Phase 2 (Data Transformation Specification):**

1. **Use this document** as the complete frontend target specification
2. **Map each backend API response** to the exact field structures documented above
3. **Design transformation logic** for all calculated fields and derived values
4. **Address critical data gaps** by ensuring backend APIs provide missing data
5. **Plan error handling** for data validation and type conversion failures
6. **Consider performance** implications for large datasets and real-time updates

**Success Criteria for Phase 2**: Every field in this specification has a clear transformation path from backend API to frontend component.

---

**Document Status**: ✅ COMPLETE  
**Ready for Phase 2**: ✅ YES  
**Critical Issues Identified**: ⚠️ 6 fields using Math.random() require immediate API integration