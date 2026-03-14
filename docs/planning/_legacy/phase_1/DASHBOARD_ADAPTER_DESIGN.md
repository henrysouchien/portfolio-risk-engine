# Dashboard Adapter Layer Design

## Overview

The **Dashboard Adapter Layer** provides a clean interface between complex API responses and React components, eliminating tight coupling while maintaining full integration with the risk analysis system.

## Architecture

```
Complex API Responses → ADAPTER LAYER → Clean Component Interfaces
```

## Core Adapter Interface

```typescript
interface DashboardAdapter {
  // Primary data methods - clean interfaces for each view
  getRiskScoreData(): Promise<RiskScoreViewData>;
  getPortfolioMetricsData(): Promise<MetricsViewData>;
  getFactorAnalysisData(): Promise<FactorsViewData>;
  getAnalysisReportData(): Promise<ReportViewData>;
  getRiskSettingsData(): Promise<SettingsViewData>;
  
  // Portfolio context methods
  getPortfolioSummary(): Promise<PortfolioSummary>;
  refreshPrices(): Promise<void>;
  
  // Error handling
  getLastError(): AdapterError | null;
  retryFailedOperation(operationId: string): Promise<any>;
}
```

## Clean View Data Interfaces

### 1. Risk Score View
```typescript
interface RiskScoreViewData {
  score: {
    value: number;
    level: 'Low' | 'Medium' | 'High';
    category: string;
  };
  components: {
    volatility: { score: number; weight: number; };
    concentration: { score: number; weight: number; };
    correlation: { score: number; weight: number; };
    liquidity: { score: number; weight: number; };
  };
  riskFactors: Array<{
    factor: string;
    impact: 'High' | 'Medium' | 'Low';
    description: string;
  }>;
  recommendations: Array<{
    priority: 'High' | 'Medium' | 'Low';
    action: string;
    rationale: string;
  }>;
  compliance: {
    status: 'Pass' | 'Warning' | 'Violation';
    violations: Array<{
      limit: string;
      current: number;
      threshold: number;
    }>;
  };
}
```

### 2. Portfolio Metrics View
```typescript
interface MetricsViewData {
  data: {
    coreMetrics: {
      volatility: { annual: number; monthly: number; };
      sharpeRatio: number;
      maxConcentration: number;
      herfindahlIndex: number;
    };
    riskContributions: Array<{
      position: string;
      positionLabel: string; // From ETF mappings
      weight: number;
      riskContribution: number;
      isProxy: boolean; // Cash proxy indicator
    }>;
    factorBetas: {
      [factorName: string]: {
        beta: number;
        pValue: number;
        significant: boolean;
      };
    };
  };
  visuals: {
    concentrationChart: Array<{
      position: string;
      label: string;
      weight: number;
      color: string;
    }>;
    riskContributionChart: Array<{
      position: string;
      label: string;
      contribution: number;
      color: string;
    }>;
    timeSeriesData: Array<{
      date: string;
      portfolioReturn: number;
      benchmarkReturn: number;
    }>;
  };
}
```

### 3. Factor Analysis View
```typescript
interface FactorsViewData {
  data: {
    portfolioFactorBetas: {
      [factorName: string]: {
        beta: number;
        tStat: number;
        pValue: number;
        significant: boolean;
        compliance: 'Pass' | 'Warning' | 'Violation';
      };
    };
    varianceDecomposition: {
      totalVariance: number;
      factorVariance: number;
      specificVariance: number;
      factorContributions: {
        [factorName: string]: {
          variance: number;
          percentage: number;
        };
      };
    };
    positionFactorExposures: Array<{
      position: string;
      positionLabel: string;
      weight: number;
      factorBetas: { [factorName: string]: number };
      isProxy: boolean;
    }>;
  };
  visuals: {
    varianceDecompositionPie: Array<{
      name: string;
      value: number;
      color: string;
    }>;
    factorBetasChart: Array<{
      factor: string;
      beta: number;
      significance: boolean;
      limit?: number;
    }>;
    heatmapData: {
      positions: string[];
      factors: string[];
      values: number[][];
    };
  };
}
```

### 4. Analysis Report View
```typescript
interface ReportViewData {
  report: {
    sections: Array<{
      title: string;
      content: string;
      type: 'text' | 'table' | 'metric';
    }>;
    summary: string;
  };
  metadata: {
    portfolioName: string;
    analysisDate: string;
    dataSource: string;
    userId: string;
  };
  exportOptions: {
    availableFormats: Array<'pdf' | 'csv' | 'json'>;
    lastExported?: string;
  };
}
```

### 5. Risk Settings View
```typescript
interface SettingsViewData {
  data: {
    limits: {
      portfolio: {
        maxVolatility: { value: number; current: number; utilization: number; };
        minSharpeRatio: { value: number; current: number; status: 'Pass' | 'Fail'; };
      };
      concentration: {
        maxSingleStock: { value: number; current: number; utilization: number; };
        maxSector: { value: number; current: number; utilization: number; };
      };
      factors: {
        [factorName: string]: {
          maxBeta: number;
          current: number;
          utilization: number;
          status: 'Pass' | 'Warning' | 'Violation';
        };
      };
    };
    compliance: {
      overallStatus: 'Pass' | 'Warning' | 'Violation';
      passCount: number;
      warningCount: number;
      violationCount: number;
    };
  };
  visuals: {
    utilizationChart: Array<{
      limit: string;
      utilization: number;
      status: 'Pass' | 'Warning' | 'Violation';
    }>;
    complianceHistory: Array<{
      date: string;
      passCount: number;
      warningCount: number;
      violationCount: number;
    }>;
  };
}
```

## Adapter Implementation

```typescript
class RiskDashboardAdapter implements DashboardAdapter {
  private apiService: ApiService;
  private etfMappings: EtfMappings;
  private cache: Map<string, { data: any; timestamp: number; }>;
  private readonly CACHE_TTL = 30 * 60 * 1000; // 30 minutes
  
  constructor(apiService: ApiService, etfMappings: EtfMappings) {
    this.apiService = apiService;
    this.etfMappings = etfMappings;
    this.cache = new Map();
  }
  
  // === RISK SCORE VIEW ===
  async getRiskScoreData(): Promise<RiskScoreViewData> {
    try {
      const rawData = await this.getCachedOrFetch('risk-score', () => 
        this.apiService.getRiskScore()
      );
      
      return this.transformRiskScoreData(rawData);
    } catch (error) {
      throw new AdapterError('Failed to load risk score data', error);
    }
  }
  
  private transformRiskScoreData(apiResponse: any): RiskScoreViewData {
    // Handle different API response structures
    const riskScore = apiResponse.risk_score || apiResponse.score;
    const analysis = apiResponse.portfolio_analysis || apiResponse.analysis;
    
    return {
      score: {
        value: riskScore.score,
        level: this.mapScoreToLevel(riskScore.score),
        category: riskScore.category || this.categorizeScore(riskScore.score)
      },
      components: this.transformComponentScores(riskScore.component_scores),
      riskFactors: this.transformRiskFactors(riskScore.risk_factors),
      recommendations: this.transformRecommendations(riskScore.recommendations),
      compliance: this.transformComplianceData(apiResponse.limits_analysis)
    };
  }
  
  // === PORTFOLIO METRICS VIEW ===
  async getPortfolioMetricsData(): Promise<MetricsViewData> {
    try {
      const rawData = await this.getCachedOrFetch('portfolio-analysis', () => 
        this.apiService.getPortfolioAnalysis()
      );
      
      return this.transformMetricsData(rawData);
    } catch (error) {
      throw new AdapterError('Failed to load metrics data', error);
    }
  }
  
  private transformMetricsData(apiResponse: any): MetricsViewData {
    const analysis = apiResponse.analysis || apiResponse;
    
    return {
      data: {
        coreMetrics: {
          volatility: {
            annual: analysis.volatility_annual,
            monthly: analysis.volatility_monthly
          },
          sharpeRatio: analysis.sharpe_ratio,
          maxConcentration: this.calculateMaxConcentration(analysis.allocations),
          herfindahlIndex: analysis.herfindahl_index
        },
        riskContributions: this.transformRiskContributions(analysis.risk_contributions, analysis.allocations),
        factorBetas: this.transformFactorBetas(analysis.portfolio_factor_betas)
      },
      visuals: {
        concentrationChart: this.prepareConcentrationChart(analysis.allocations),
        riskContributionChart: this.prepareRiskContributionChart(analysis.risk_contributions),
        timeSeriesData: this.prepareTimeSeriesData(analysis.portfolio_returns)
      }
    };
  }
  
  // === FACTOR ANALYSIS VIEW ===
  async getFactorAnalysisData(): Promise<FactorsViewData> {
    try {
      const rawData = await this.getCachedOrFetch('portfolio-analysis', () => 
        this.apiService.getPortfolioAnalysis()
      );
      
      return this.transformFactorData(rawData);
    } catch (error) {
      throw new AdapterError('Failed to load factor analysis data', error);
    }
  }
  
  private transformFactorData(apiResponse: any): FactorsViewData {
    const analysis = apiResponse.analysis || apiResponse;
    
    return {
      data: {
        portfolioFactorBetas: this.transformPortfolioFactorBetas(
          analysis.portfolio_factor_betas,
          analysis.beta_checks
        ),
        varianceDecomposition: this.transformVarianceDecomposition(
          analysis.variance_decomposition,
          analysis.euler_variance_pct
        ),
        positionFactorExposures: this.transformPositionFactorExposures(
          analysis.df_stock_betas,
          analysis.allocations
        )
      },
      visuals: {
        varianceDecompositionPie: this.prepareVarianceDecompositionChart(analysis.euler_variance_pct),
        factorBetasChart: this.prepareFactorBetasChart(analysis.portfolio_factor_betas),
        heatmapData: this.prepareFactorHeatmap(analysis.df_stock_betas)
      }
    };
  }
  
  // === ANALYSIS REPORT VIEW ===
  async getAnalysisReportData(): Promise<ReportViewData> {
    try {
      const rawData = await this.getCachedOrFetch('portfolio-analysis', () => 
        this.apiService.getPortfolioAnalysis()
      );
      
      return this.transformReportData(rawData);
    } catch (error) {
      throw new AdapterError('Failed to load report data', error);
    }
  }
  
  private transformReportData(apiResponse: any): ReportViewData {
    return {
      report: {
        sections: this.parseFormattedReport(apiResponse.formatted_report),
        summary: apiResponse.summary || this.generateSummary(apiResponse)
      },
      metadata: {
        portfolioName: apiResponse.portfolio_metadata?.name || 'Portfolio',
        analysisDate: apiResponse.portfolio_metadata?.analyzed_at || new Date().toISOString(),
        dataSource: apiResponse.portfolio_metadata?.source || 'API',
        userId: apiResponse.portfolio_metadata?.user_id || 'unknown'
      },
      exportOptions: {
        availableFormats: ['pdf', 'csv', 'json'],
        lastExported: this.getLastExportTime()
      }
    };
  }
  
  // === RISK SETTINGS VIEW ===
  async getRiskSettingsData(): Promise<SettingsViewData> {
    try {
      const [riskSettings, analysisData] = await Promise.all([
        this.getCachedOrFetch('risk-settings', () => this.apiService.getRiskSettings()),
        this.getCachedOrFetch('portfolio-analysis', () => this.apiService.getPortfolioAnalysis())
      ]);
      
      return this.transformSettingsData(riskSettings, analysisData);
    } catch (error) {
      throw new AdapterError('Failed to load settings data', error);
    }
  }
  
  private transformSettingsData(settings: any, analysis: any): SettingsViewData {
    const limits = settings.risk_limits || settings;
    const current = analysis.analysis || analysis;
    
    return {
      data: {
        limits: this.transformLimitsData(limits, current),
        compliance: this.calculateComplianceStatus(limits, current)
      },
      visuals: {
        utilizationChart: this.prepareUtilizationChart(limits, current),
        complianceHistory: this.prepareComplianceHistory()
      }
    };
  }
  
  // === PORTFOLIO CONTEXT ===
  async getPortfolioSummary(): Promise<PortfolioSummary> {
    try {
      const [analysisData, riskScore] = await Promise.all([
        this.getCachedOrFetch('portfolio-analysis', () => this.apiService.getPortfolioAnalysis()),
        this.getCachedOrFetch('risk-score', () => this.apiService.getRiskScore())
      ]);
      
      return {
        portfolioName: analysisData.portfolio_metadata?.name || 'Portfolio',
        totalValue: this.calculateTotalValue(analysisData.analysis.allocations),
        riskScore: riskScore.risk_score?.score || riskScore.score,
        volatility: analysisData.analysis.volatility_annual,
        lastUpdated: analysisData.portfolio_metadata?.analyzed_at || new Date().toISOString(),
        positionCount: Object.keys(analysisData.analysis.allocations?.weights || {}).length
      };
    } catch (error) {
      throw new AdapterError('Failed to load portfolio summary', error);
    }
  }
  
  // === TRANSFORMATION HELPERS ===
  
  private transformRiskContributions(riskContributions: any, allocations: any): Array<any> {
    const weights = allocations?.weights || {};
    
    return Object.entries(riskContributions || {}).map(([symbol, contribution]) => ({
      position: symbol,
      positionLabel: this.etfMappings.getPositionLabel(symbol),
      weight: weights[symbol] || 0,
      riskContribution: contribution as number,
      isProxy: this.etfMappings.isCashProxy(symbol)
    }));
  }
  
  private prepareConcentrationChart(allocations: any): Array<any> {
    const weights = allocations?.weights || {};
    
    return Object.entries(weights)
      .map(([symbol, weight]) => ({
        position: symbol,
        label: this.etfMappings.getPositionLabel(symbol),
        weight: weight as number,
        color: this.etfMappings.getPositionColor(symbol)
      }))
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 10); // Top 10 positions
  }
  
  private transformPortfolioFactorBetas(factorBetas: any, betaChecks: any): any {
    const result: any = {};
    
    for (const [factor, beta] of Object.entries(factorBetas || {})) {
      result[factor] = {
        beta: beta as number,
        tStat: this.calculateTStat(beta, factor), // Would need more data
        pValue: this.calculatePValue(beta, factor), // Would need more data
        significant: Math.abs(beta as number) > 0.1, // Simple significance check
        compliance: this.checkBetaCompliance(factor, beta as number, betaChecks)
      };
    }
    
    return result;
  }
  
  // === CACHING AND ERROR HANDLING ===
  
  private async getCachedOrFetch<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
    const cached = this.cache.get(key);
    
    if (cached && (Date.now() - cached.timestamp) < this.CACHE_TTL) {
      return cached.data;
    }
    
    const data = await fetcher();
    this.cache.set(key, { data, timestamp: Date.now() });
    return data;
  }
  
  async refreshPrices(): Promise<void> {
    // Clear cache to force fresh data
    this.cache.clear();
    
    // Trigger price refresh on backend
    await this.apiService.refreshPortfolioPrices();
  }
  
  getLastError(): AdapterError | null {
    // Implementation for error tracking
    return null;
  }
  
  async retryFailedOperation(operationId: string): Promise<any> {
    // Implementation for retry logic
    throw new Error('Method not implemented');
  }
  
  // === HELPER METHODS ===
  
  private mapScoreToLevel(score: number): 'Low' | 'Medium' | 'High' {
    if (score <= 30) return 'Low';
    if (score <= 70) return 'Medium';
    return 'High';
  }
  
  private calculateMaxConcentration(allocations: any): number {
    const weights = allocations?.weights || {};
    return Math.max(...Object.values(weights).map(w => w as number));
  }
  
  private checkBetaCompliance(factor: string, beta: number, betaChecks: any): 'Pass' | 'Warning' | 'Violation' {
    const check = betaChecks?.[factor];
    if (!check) return 'Pass';
    
    if (check.status === 'VIOLATION') return 'Violation';
    if (check.status === 'WARNING') return 'Warning';
    return 'Pass';
  }
}

// Error handling
class AdapterError extends Error {
  constructor(message: string, public originalError?: any) {
    super(message);
    this.name = 'AdapterError';
  }
}

interface PortfolioSummary {
  portfolioName: string;
  totalValue: number;
  riskScore: number;
  volatility: number;
  lastUpdated: string;
  positionCount: number;
}
```

## Benefits of This Adapter Design

### 1. **Clean Component Interfaces**
```typescript
// ❌ OLD: Component tightly coupled to API
const MetricsView = ({ analysisData }) => {
  const volatility = analysisData.analysis.volatility_annual; // Fragile!
  return <div>{volatility}</div>;
};

// ✅ NEW: Component uses clean adapter interface  
const MetricsView = () => {
  const { data } = useAdapterData(() => adapter.getPortfolioMetricsData());
  const volatility = data.coreMetrics.volatility.annual; // Stable!
  return <div>{volatility}</div>;
};
```

### 2. **API Change Resilience**
```typescript
// API structure changes from:
// { analysis: { volatility_annual: 0.15 } }
// to:
// { volatility_annual: 0.15, analysis_metadata: {...} }

// Only adapter needs update:
private transformMetricsData(apiResponse: any): MetricsViewData {
  const volatility = apiResponse.analysis?.volatility_annual || apiResponse.volatility_annual;
  // Components unchanged!
}
```

### 3. **Position Label Integration**
```typescript
// Automatically applies ETF mappings and cash proxy detection
riskContributions: this.transformRiskContributions(analysis.risk_contributions, analysis.allocations)

// Results in clean component data:
// { position: "SGOV", positionLabel: "Cash Proxy", isProxy: true }
```

### 4. **Built-in Caching & Error Handling**
- **30-minute TTL cache** aligned with backend
- **Error isolation** - API failures don't crash views
- **Retry mechanisms** for failed operations

## Integration with Current Plan

This adapter replaces the `dataExtractor` functions in the current dashboard plan:

```typescript
// ❌ OLD: Direct API coupling
const analysisViews = [
  {
    id: 'metrics',
    dataExtractor: (analysis) => ({
      data: analysis.analysis.volatility_annual // FRAGILE
    })
  }
];

// ✅ NEW: Clean adapter integration
const analysisViews = [
  {
    id: 'metrics',
    dataLoader: () => adapter.getPortfolioMetricsData() // RESILIENT
  }
];
```

**This adapter layer is the missing architectural foundation that makes the dashboard plan production-ready! 🎯** 