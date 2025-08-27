# Chat + Artifacts Architecture Design Document

## Overview

This document outlines the design and implementation strategy for integrating **Claude Chat + Interactive Artifacts** into the existing portfolio risk analysis platform. The goal is to enable users to interact with their portfolio data through natural language conversations while generating interactive visualizations they can manipulate directly.

## Table of Contents

1. [Strategic Vision & Value Pillars](#strategic-vision--value-pillars)
2. [Architecture Vision](#architecture-vision)
3. [Current Architecture Analysis](#current-architecture-analysis)
4. [Chat Integration Design](#chat-integration-design)
5. [Artifact System Architecture](#artifact-system-architecture)
6. [Chart Slots Evolution](#chart-slots-evolution)
7. [Type-Safe Data Flow Architecture](#type-safe-data-flow-architecture)
8. [Backend Extensions](#backend-extensions)
9. [Implementation Strategy](#implementation-strategy)
10. [User Experience Design](#user-experience-design)
11. [Security & Sandboxing](#security--sandboxing)
12. [Migration Plan](#migration-plan)

---

## Strategic Vision & Value Pillars

### **Core Strategic Opportunity**

We're building the **first AI-native portfolio intelligence platform** - not just adding AI to existing tools, but designing intelligence into the foundation. Our unique advantage is building from the ground up with:

- **Sophisticated Risk Analysis**: Professional-grade portfolio analytics
- **Rich User Context**: Deep understanding of user goals, timeline, and preferences  
- **Modern AI Integration**: Claude function calling, artifacts, and conversational intelligence
- **Full Stack Control**: Optimized experience from backend data to frontend interaction

### **Value Proposition: AI-Powered Portfolio Copilot**

#### **Traditional vs. AI-Native Approach**
```
❌ TRADITIONAL PORTFOLIO TOOLS:
User: *stares at dashboard* 
Tool: "Risk score: 73" 
User: "...so what do I do about it?"
Tool: *crickets*

✅ OUR AI-NATIVE INTELLIGENCE:
User: "I'm concerned about my retirement portfolio"
AI: "I see your risk increased to 73 due to tech concentration. 
     Given your 15-year timeline and moderate risk tolerance,
     here's an interactive scenario showing 3 rebalancing options..."
*Generates artifact with sliders to test strategies*
User: *adjusts allocation in artifact*
AI: "That change reduces risk to 68 and only costs 0.2% expected return.
     Shall I show you exactly which trades to make?"
```

### **Four Strategic Value Pillars**

#### **Pillar 1: Intent-Aware Financial Intelligence**
**Goal**: Understand WHY users are asking, not just WHAT they're asking

**Technical Integration**: 
```typescript
// Context engine that informs all AI interactions
interface UserIntent {
  goal: "retirement_planning" | "risk_management" | "performance_optimization";
  timeHorizon: string;          // "15_years"
  riskTolerance: string;        // "moderate" 
  currentConcern: string;       // "portfolio_volatility"
  marketContext: string;        // "rising_rates"
  urgency: "planning" | "crisis";
}

// Every Claude interaction gets this context
const enhancedChatRequest = {
  user_message: userInput,
  intent_context: userIntent,        // NEW: Intent understanding
  portfolio_context: portfolioData,  // Existing rich portfolio data
  market_context: marketData,        // NEW: External context integration
  user_history: behaviorPatterns     // NEW: Learning from user patterns
};
```

**Value**: AI provides contextually appropriate guidance instead of generic responses

#### **Pillar 2: Proactive Decision Support**  
**Goal**: Anticipate what users need before they ask

**Technical Integration**:
```python
# Backend intelligence that monitors and alerts
class ProactiveIntelligenceEngine:
    def __init__(self):
        self.portfolio_monitor = YourExistingRiskAnalysis()
        self.claude_ai = ClaudeChatService()
        self.intent_predictor = IntentPredictionService()
    
    async def monitor_user_portfolio(self, user_id):
        # Existing risk analysis + proactive intelligence
        portfolio_state = await self.portfolio_monitor.analyze(user_id)
        
        # NEW: Detect emerging issues
        concerns = self.detect_emerging_concerns(portfolio_state, user_context)
        
        if concerns:
            # Generate proactive Claude analysis
            proactive_insight = await self.claude_ai.generate_proactive_alert(
                concerns=concerns,
                user_context=user_context,
                suggested_artifacts=["risk_dashboard", "stress_tester"]
            )
            
            return proactive_insight
```

**Value**: Users discover issues before they become expensive problems

#### **Pillar 3: Real-Time What-If Intelligence**
**Goal**: Instant scenario exploration with AI guidance

**Technical Integration**:
```typescript
// Enhanced artifacts with AI-guided exploration
const ScenarioExplorationArtifact = () => {
  const [scenarioResults, setScenarioResults] = useState();
  
  const handleScenarioChange = useCallback(async (changes) => {
    // Real-time portfolio calculation (existing)
    const newResults = await portfolioAPI.runWhatIfScenario(changes);
    
    // NEW: AI interpretation of results
    const aiInsight = await claudeService.interpretScenarioResults({
      changes: changes,
      results: newResults,
      user_context: userContext,
      previous_scenarios: scenarioHistory
    });
    
    setScenarioResults({ 
      data: newResults, 
      aiGuidance: aiInsight  // AI explains what the numbers mean
    });
  }, []);
  
  return (
    <div className="scenario-explorer">
      <InteractiveSliders onChange={handleScenarioChange} />
      <ResultsVisualization data={scenarioResults.data} />
      <AIGuidance insight={scenarioResults.aiGuidance} />  {/* NEW */}
    </div>
  );
};
```

**Value**: Users can explore complex scenarios with AI explaining implications

#### **Pillar 4: Contextual Learning & Adaptation**
**Goal**: System learns user patterns and adapts over time

**Technical Integration**:
```python
# Learning system that enhances all interactions
class UserIntelligenceService:
    def __init__(self):
        self.pattern_analyzer = UserPatternAnalyzer()
        self.preference_engine = PreferenceEngine()
        
    def enhance_claude_interaction(self, user_id, interaction_request):
        # Learn from user behavior
        user_patterns = self.pattern_analyzer.analyze_user_patterns(user_id)
        preferences = self.preference_engine.get_communication_preferences(user_id)
        
        # Enhance Claude context with learned patterns
        enhanced_request = {
            **interaction_request,
            user_patterns: user_patterns,           # How user makes decisions
            communication_style: preferences.style, # How user likes explanations
            risk_framing: preferences.risk_style,   # How to present risk information
            decision_timing: patterns.urgency       # How quickly user typically acts
        }
        
        return enhanced_request
```

**Value**: System becomes more helpful over time, like a personal advisor who knows you

### **Competitive Differentiation**

| **Competitor Type** | **Their Approach** | **Our AI-Native Advantage** |
|---|---|---|
| **Traditional Portfolio Tools** (Morningstar, etc.) | Static analysis, user interprets data alone | AI copilot that understands intent and guides decisions |
| **Robo-Advisors** (Betterment, etc.) | Automated allocation with limited customization | Intelligent collaboration - AI + human decision making |
| **Professional Advisors** | Expensive, periodic check-ins, limited availability | 24/7 AI advisor with professional-grade analysis |

### **User Value Propositions**

#### **For Individual Investors**
- **"Like having a portfolio manager, risk analyst, and financial planner as your AI copilots"**
- 24/7 intelligent guidance instead of quarterly advisor meetings
- Proactive alerts before problems become expensive  
- Interactive scenario planning for major life decisions

#### **For Professional Advisors**
- **"AI-powered analysis that makes you 10x more effective"**
- Instant comprehensive analysis for client meetings
- Scenario modeling for client education
- Risk monitoring across entire client base

#### **For Institutions**
- **"Portfolio intelligence that scales across thousands of accounts"**
- Consistent risk management with AI oversight
- Regulatory compliance with audit trails
- Custom analysis for institutional needs

### **Integration with Technical Architecture**

#### **How Pillars Map to Technical Components**

**Pillar 1 (Intent-Aware Intelligence)** → Enhanced Claude Service + Context Engine
- Extend existing `ClaudeChatService` with intent detection
- Add market context and user behavior analysis
- Enhance portfolio context with goal-based analysis

**Pillar 2 (Proactive Decision Support)** → Background Monitoring + Intelligent Alerts
- Build on existing risk analysis for proactive monitoring
- Create alert system that generates Claude-powered insights
- Add notification system for emerging portfolio issues

**Pillar 3 (Real-Time What-If Intelligence)** → Enhanced Artifacts + AI Interpretation
- Extend existing chart slots with AI-guided exploration
- Add real-time Claude interpretation of scenario results
- Create artifact templates for common decision scenarios

**Pillar 4 (Contextual Learning & Adaptation)** → User Intelligence Layer
- Add user pattern analysis to existing analytics
- Enhance authentication system with preference learning
- Integrate learned preferences into all Claude interactions

### **Implementation Priority**

These pillars guide our implementation strategy:

1. **Phase 1**: Foundation + Pillar 1 (Intent-Aware Intelligence)
2. **Phase 2**: Pillar 3 (Real-Time What-If Intelligence) via interactive artifacts
3. **Phase 3**: Pillar 2 (Proactive Decision Support) with monitoring
4. **Phase 4**: Pillar 4 (Contextual Learning & Adaptation) for personalization

---

## Architecture Vision

### **Core Concept**
Transform the existing dashboard-driven portfolio analysis platform into a **dual-interface system**:
- **Traditional Dashboard**: Current sophisticated dashboard interface (preserved)
- **Chat + Artifacts**: Natural language interface with interactive visualizations

### **User Experience Goals**
```
User: "Show me my portfolio risk breakdown"
Claude: Creates interactive risk dashboard artifact + explains insights

User: Adjusts allocation sliders in the artifact
Claude: "I see you increased bonds to 40%. This reduces your risk score from 65 to 78..."

User: "Now optimize this for better returns"
Claude: Creates optimization artifact + runs analysis functions
```

### **Key Principles**
- **Extend, Don't Replace**: Leverage existing architecture rather than rebuilding
- **Dual-Purpose Components**: Chart slots work in both dashboard and artifact contexts
- **Context-Aware Intelligence**: Claude understands user's portfolio and current view
- **Progressive Enhancement**: Can be implemented in phases without breaking existing functionality

---

## Current Architecture Analysis

### **Existing Frontend Architecture (React/TypeScript)**
```typescript
// Current Provider Hierarchy (EXCELLENT FOUNDATION)
<QueryProvider>          // ← React Query for server state
  <AuthProvider>         // ← Authentication & user context
    <SessionServicesProvider>  // ← User-scoped services
      <AppOrchestrator />      // ← Routes between app experiences
    </SessionServicesProvider>
  </AuthProvider>
</QueryProvider>
```

**Strengths for Chat Integration:**
✅ **Multi-user isolation** already implemented
✅ **Portfolio context** available through SessionServicesProvider
✅ **Authentication flow** with secure sessions
✅ **Sophisticated chart slots** system already exists
✅ **Claude integration** already working (ClaudeService.ts)

### **Existing Backend Architecture (FastAPI/Python)**
```python
# Current Claude Integration (PERFECT FOR ARTIFACTS)
class ClaudeChatService:
    - Comprehensive function calling system ✅
    - Portfolio context integration ✅  
    - Multi-round function chains ✅
    - Token optimization & caching ✅
    - User isolation & security ✅
```

**Strengths for Artifact System:**
✅ **Function calling** can provide data to artifacts
✅ **Portfolio context** already enriches Claude conversations
✅ **Result objects** with beautiful CLI formatting
✅ **Secure multi-user** architecture

### **Existing Chart Slots System**
```typescript
// Current Slot Architecture (PERFECT FOR DUAL-PURPOSE)
export const RiskContributionSlot: React.FC<SlotProps> = ({
  factorData,        // ← Data from adapters
  loading,           // ← State handling
  error,             // ← Error handling  
  height,            // ← Flexible configuration
  title              // ← Customizable display
}) => {
  // Transform data using existing adapters
  const chartData = adaptRiskContributionData(factorData);
  // Render with loading/error states
};
```

**Perfect Foundation for Artifacts:**
✅ **Data adaptation** via existing adapters
✅ **State management** (loading, error, empty)
✅ **Flexible configuration** (titles, heights, styling)
✅ **Reusable components** ready for artifact context

---

## Chat Integration Design

### **Frontend Architecture Extension**

#### **1. Enhanced Provider Hierarchy**
```typescript
// MINIMAL ADDITION to existing hierarchy
const App: FC = () => {
  return (
    <QueryProvider>
      <AuthProvider>
        <SessionServicesProvider>
          <ArtifactProvider>  {/* NEW: Adds artifact execution capability */}
            <AppOrchestrator />
          </ArtifactProvider>
        </SessionServicesProvider>
      </AuthProvider>
    </QueryProvider>
  );
};
```

#### **2. Extended AppOrchestrator**
```typescript
// ADD chat interface option to existing orchestrator
const AppOrchestrator = () => {
  const { isAuthenticated } = useAuth();
  const [interface, setInterface] = useState<'dashboard' | 'chat'>('dashboard');
  
  if (!isAuthenticated) return <LandingApp />;
  
  return (
    <>
      <InterfaceSwitcher 
        current={interface} 
        onChange={setInterface}
        options={[
          { value: 'dashboard', label: '📊 Dashboard View' },
          { value: 'chat', label: '💬 Chat + Artifacts' }  // NEW
        ]}
      />
      
      {interface === 'dashboard' && <DashboardApp />}     // Existing
      {interface === 'chat' && <ChatArtifactInterface />} // NEW
    </>
  );
};
```

#### **3. Chat Interface Architecture**
```typescript
// New chat interface leveraging existing services
const ChatArtifactInterface = () => {
  const { user } = useAuth();                    // Existing auth context
  const { portfolioService } = useSessionServices(); // Existing portfolio services
  const { executeArtifact } = useArtifacts();    // NEW artifact capability
  
  return (
    <div className="chat-artifact-layout">
      {/* LEFT PANEL: Chat conversation */}
      <ChatPanel 
        claudeService={portfolioService.claudeService}  // Use existing Claude service
        portfolioContext={portfolioService.context}     // Use existing portfolio context
        onArtifactCreated={(artifact) => executeArtifact(artifact)}
      />
      
      {/* RIGHT PANEL: Active artifacts */}
      <ArtifactPanel />
    </div>
  );
};
```

### **Context Provider Architecture**

#### **Frontend as Context Provider**
```typescript
const sendMessage = async (userMessage: string) => {
  const contextualMessage = {
    user_message: userMessage,
    
    // RICH CONTEXT from existing architecture
    portfolio_id: currentPortfolio.id,
    portfolio_name: currentPortfolio.name,
    user_session: getCurrentSession(),
    
    // UI STATE CONTEXT
    current_view: "chat",
    recent_actions: getRecentUserActions(),
    
    // USER PREFERENCE CONTEXT  
    preferred_communication: user.preferences.style,
    risk_tolerance: user.profile.riskTolerance,
    
    // CHAT HISTORY
    chat_history: messages
  };
  
  // Send rich context to Claude
  await claudeService.sendMessageWithArtifacts(contextualMessage);
};
```

#### **Intent Guidance System**
```typescript
const IntentGuides = () => {
  const currentContext = usePortfolioContext();
  
  // Smart suggestions based on current portfolio state
  const contextualSuggestions = useMemo(() => {
    if (currentContext.riskScore < 60) {
      return [
        "🚨 My portfolio seems risky - help me understand why",
        "🛡️ How can I reduce my portfolio risk?", 
        "📊 Show me what's driving my risk"
      ];
    }
    
    if (currentContext.lastRebalance > 90) { // days ago
      return [
        "⚖️ Should I rebalance my portfolio?",
        "📈 Any opportunities to improve my allocation?",
        "🔍 How has my portfolio drifted since last rebalance?"
      ];
    }
    
    return [
      "💡 Any recommendations for my portfolio?",
      "📊 How is my portfolio performing?", 
      "🎯 Am I on track with my investment goals?"
    ];
  }, [currentContext]);
  
  return (
    <div className="intent-guides">
      <h4>Try asking:</h4>
      {contextualSuggestions.map(suggestion => (
        <button 
          key={suggestion}
          onClick={() => sendMessage(suggestion)}
          className="intent-suggestion"
        >
          {suggestion}
        </button>
      ))}
    </div>
  );
};
```

---

## Artifact System Architecture

### **Sandboxed React Environment**

#### **1. Secure Artifact Execution**
```typescript
class ArtifactSandbox {
  private allowedLibraries = [
    'react', 'useState', 'useEffect', 'useMemo', 'useCallback',
    'recharts', // For charts
    'lodash', 'date-fns' // Utility libraries
  ];
  
  private portfolioAPIProxy: SecurePortfolioProxy;
  
  constructor(portfolioService: PortfolioService) {
    this.portfolioAPIProxy = this.createSecureProxy(portfolioService);
  }
  
  async executeArtifact(artifact: ArtifactSpec): Promise<ReactComponent> {
    // Parse and validate React component code
    const component = this.parseReactComponent(artifact.componentCode);
    
    // Create secure execution context
    const secureContext = {
      // Safe React hooks
      React, useState, useEffect, useMemo, useCallback,
      
      // Chart libraries
      recharts: { PieChart, BarChart, LineChart, ResponsiveContainer },
      
      // Secure portfolio API
      portfolioAPI: this.portfolioAPIProxy,
      
      // Artifact data
      portfolioData: this.sanitizeData(artifact.data)
    };
    
    // Execute in isolated context
    return this.renderInSandbox(component, secureContext);
  }
  
  private createSecureProxy(portfolioService: PortfolioService) {
    return {
      // ALLOW: Safe read operations
      getCurrentPortfolio: () => portfolioService.getCurrentPortfolio(),
      getRiskAnalysis: () => portfolioService.getRiskAnalysis(),
      runScenario: (weights) => portfolioService.runWhatIfScenario(weights),
      calculateRisk: (weights) => portfolioService.calculateRisk(weights),
      
      // BLOCK: Dangerous operations
      savePortfolio: () => { throw new Error('Write operations not allowed in artifacts'); },
      deletePortfolio: () => { throw new Error('Delete operations not allowed in artifacts'); },
      // Block all network access except through controlled proxy
    };
  }
}
```

#### **2. Artifact Provider Integration**
```typescript
const ArtifactProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const { portfolioService } = useSessionServices(); // Use existing services
  const [activeArtifacts, setActiveArtifacts] = useState<Artifact[]>([]);
  
  const executeArtifact = useCallback(async (artifactSpec: ArtifactSpec) => {
    // Create secure sandbox using existing portfolio service
    const sandbox = new ArtifactSandbox(portfolioService);
    
    try {
      const executedArtifact = await sandbox.execute(artifactSpec);
      setActiveArtifacts(prev => [...prev, executedArtifact]);
      
      return executedArtifact;
    } catch (error) {
      console.error('Artifact execution failed:', error);
      throw new ArtifactExecutionError(error.message);
    }
  }, [portfolioService]);
  
  const handleArtifactInteraction = useCallback((artifactId: string, interaction: ArtifactInteraction) => {
    // User manipulated artifact - send context back to Claude
    const artifact = activeArtifacts.find(a => a.id === artifactId);
    if (artifact && interaction.triggersChatResponse) {
      // Send interaction context to Claude for follow-up analysis
      return portfolioService.claudeService.sendMessage(
        `Based on my changes to the ${artifact.name}: ${interaction.description}`,
        { artifact_context: interaction.data }
      );
    }
  }, [activeArtifacts, portfolioService]);
  
  return (
    <ArtifactContext.Provider value={{ 
      activeArtifacts, 
      executeArtifact, 
      handleArtifactInteraction 
    }}>
      {children}
    </ArtifactContext.Provider>
  );
};
```

### **Artifact Types & Templates**

#### **Portfolio-Specific Artifact Library**
```typescript
interface PortfolioArtifactTypes {
  // Risk Analysis Artifacts
  risk_dashboard: {
    slots: ['PortfolioRiskMetricsSlot', 'RiskContributionSlot', 'RiskLimitChecksSlot'];
    layout: 'grid';
    interactivity: ['filtering', 'drill_down', 'cross_slot_communication'];
  };
  
  risk_contribution_analyzer: {
    slots: ['RiskContributionSlot'];
    layout: 'single';
    interactivity: ['filtering', 'stock_drill_down', 'real_time_updates'];
  };
  
  // Portfolio Optimization Artifacts  
  allocation_optimizer: {
    slots: ['PositionAnalysisSlot', 'IndustryContributionsSlot'];
    layout: 'split';
    interactivity: ['weight_adjustment', 'real_time_calculation', 'scenario_comparison'];
  };
  
  optimization_comparison: {
    slots: ['CustomOptimizationResultsSlot'];
    layout: 'tabs';
    interactivity: ['strategy_switching', 'constraint_adjustment'];
  };
  
  // Performance Analysis Artifacts
  performance_dashboard: {
    slots: ['PerformanceBenchmarkSlot', 'VarianceDecompositionSlot'];
    layout: 'vertical';
    interactivity: ['time_range_selection', 'benchmark_comparison'];
  };
  
  // Scenario Analysis Artifacts
  stress_tester: {
    slots: ['CustomStressTestSlot'];
    layout: 'interactive';
    interactivity: ['scenario_sliders', 'market_crash_simulation', 'real_time_impact'];
  };
  
  what_if_analyzer: {
    slots: ['CustomWhatIfSlot'];
    layout: 'comparison';
    interactivity: ['weight_modification', 'side_by_side_comparison'];
  };
}
```

---

## Chart Slots Evolution

### **Dual-Purpose Slot Architecture**

#### **Enhanced Slot Interface**
```typescript
// Enhanced interface supporting both dashboard and artifact contexts
interface UniversalSlotProps {
  // EXISTING: Dashboard props (unchanged)
  factorData: any;
  loading?: boolean;
  error?: string | null;
  height?: number;
  title?: string;
  description?: string;
  className?: string;
  
  // NEW: Artifact context props
  mode?: 'dashboard' | 'artifact';
  interactivity?: {
    enableFiltering?: boolean;
    enableDrillDown?: boolean;
    enableWeightAdjustment?: boolean;
    enableRealTimeUpdates?: boolean;
    onDataChange?: (interaction: SlotInteraction) => void;
    onUserAction?: (action: UserAction) => void;
  };
  artifactContext?: {
    portfolioAPI: SecurePortfolioProxy;
    chatContext: ChatContext;
    siblingSlots?: SlotReference[];
  };
}

interface SlotInteraction {
  type: 'data_filtered' | 'stock_drill_down' | 'weight_changed' | 'scenario_selected';
  source: string; // Slot identifier
  data: any;
  description: string;
  triggersChatResponse: boolean;
}
```

#### **Example: Enhanced RiskContributionSlot**
```typescript
export const RiskContributionSlot: React.FC<UniversalSlotProps> = ({
  // Existing props
  factorData,
  loading = false,
  error = null,
  height = 350,
  title = "Top Stock Risk Contributions (Pareto Analysis)",
  description = "Individual and cumulative risk contributions showing the 80/20 principle",
  className = "",
  
  // NEW: Artifact props
  mode = 'dashboard',
  interactivity = {},
  artifactContext
}) => {
  // Existing data transformation (unchanged)
  const chartData = React.useMemo(() => {
    if (!factorData) return [];
    return adaptRiskContributionData(factorData);
  }, [factorData]);
  
  // NEW: Interactive state for artifact mode
  const [selectedStocks, setSelectedStocks] = useState<string[]>([]);
  const [filteredData, setFilteredData] = useState(factorData);
  const [highlightedRisk, setHighlightedRisk] = useState<number | null>(null);
  
  // NEW: Interactive handlers for artifact mode
  const handleStockClick = useCallback((stockData) => {
    if (mode === 'artifact' && interactivity.enableDrillDown) {
      setSelectedStocks(prev => 
        prev.includes(stockData.ticker) 
          ? prev.filter(t => t !== stockData.ticker)
          : [...prev, stockData.ticker]
      );
      
      // Trigger Claude analysis of selected stock
      interactivity.onDataChange?.({
        type: 'stock_drill_down',
        source: 'RiskContributionSlot',
        data: { 
          ticker: stockData.ticker, 
          riskContribution: stockData.riskContribution,
          selected: !selectedStocks.includes(stockData.ticker)
        },
        description: `${!selectedStocks.includes(stockData.ticker) ? 'Selected' : 'Deselected'} ${stockData.ticker} for analysis`,
        triggersChatResponse: true
      });
    }
  }, [mode, interactivity, selectedStocks]);
  
  const handleRiskThresholdChange = useCallback((threshold: number) => {
    if (mode === 'artifact' && interactivity.enableFiltering) {
      const filtered = factorData.filter(stock => stock.riskContribution >= threshold);
      setFilteredData(filtered);
      setHighlightedRisk(threshold);
      
      interactivity.onDataChange?.({
        type: 'data_filtered',
        source: 'RiskContributionSlot',
        data: { threshold, filteredStocks: filtered.length, totalStocks: factorData.length },
        description: `Filtered to show stocks with >${(threshold * 100).toFixed(1)}% risk contribution`,
        triggersChatResponse: false // Don't trigger Claude for simple filtering
      });
    }
  }, [mode, interactivity, factorData]);
  
  // NEW: Real-time updates from other slots
  React.useEffect(() => {
    if (mode === 'artifact' && artifactContext?.siblingSlots) {
      const weightAdjustmentSlot = artifactContext.siblingSlots.find(s => s.type === 'weight_adjustment');
      if (weightAdjustmentSlot?.latestData) {
        // Recalculate risk contributions based on weight changes
        artifactContext.portfolioAPI.calculateRisk(weightAdjustmentSlot.latestData.weights)
          .then(newRiskData => {
            setFilteredData(newRiskData);
          });
      }
    }
  }, [mode, artifactContext]);
  
  return (
    <div className={`
      ${mode === 'artifact' ? 'artifact-slot' : 'dashboard-slot'} 
      bg-white rounded-lg border border-gray-200 p-6 
      ${className}
    `}>
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        {description && (
          <p className="text-sm text-gray-600 mt-1">{description}</p>
        )}
        
        {/* NEW: Interactive controls for artifact mode */}
        {mode === 'artifact' && interactivity.enableFiltering && (
          <div className="mt-3 flex gap-2 flex-wrap">
            <span className="text-xs text-gray-500">Filter by risk:</span>
            {[0.01, 0.03, 0.05, 0.10].map(threshold => (
              <button
                key={threshold}
                onClick={() => handleRiskThresholdChange(threshold)}
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  highlightedRisk === threshold 
                    ? 'bg-blue-500 text-white' 
                    : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                }`}
              >
                >{(threshold * 100).toFixed(0)}%
              </button>
            ))}
            <button
              onClick={() => handleRiskThresholdChange(0)}
              className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded hover:bg-gray-200"
            >
              Show All
            </button>
          </div>
        )}
        
        {/* NEW: Selected stocks indicator for artifact mode */}
        {mode === 'artifact' && selectedStocks.length > 0 && (
          <div className="mt-2 flex gap-1 flex-wrap">
            <span className="text-xs text-gray-500">Selected:</span>
            {selectedStocks.map(ticker => (
              <span key={ticker} className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded">
                {ticker}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Existing state handling (unchanged) */}
      {loading ? (
        <div className="flex justify-center items-center" style={{ height }}>
          <LoadingSpinner message="Loading risk contribution data..." />
        </div>
      ) : error ? (
        <div className="flex justify-center items-center" style={{ height }}>
          <ErrorDisplay error={error} />
        </div>
      ) : (
        <RiskContributionParetoChart
          data={chartData}
          height={height}
          showCumulative={true}
          // NEW: Interactive features for artifact mode
          onBarClick={mode === 'artifact' ? handleStockClick : undefined}
          selectedItems={mode === 'artifact' ? selectedStocks : undefined}
          highlightThreshold={mode === 'artifact' ? highlightedRisk : undefined}
          interactive={mode === 'artifact'}
          allowZoom={mode === 'artifact'}
        />
      )}
    </div>
  );
};
```

### **Slot-Based Artifact Generation**

#### **Template System**
```typescript
export const SlotArtifactTemplates = {
  // Single-slot artifacts for focused analysis
  risk_contribution_analyzer: {
    name: "Risk Contribution Analyzer",
    slots: ['RiskContributionSlot'],
    layout: 'single',
    defaultProps: {
      interactivity: {
        enableFiltering: true,
        enableDrillDown: true,
        enableRealTimeUpdates: true
      }
    },
    generatePrompt: (portfolioData) => `Interactive risk contribution analysis for portfolio with ${portfolioData.positions?.length || 0} positions`
  },
  
  // Multi-slot artifacts for comprehensive analysis
  comprehensive_risk_dashboard: {
    name: "Comprehensive Risk Dashboard",
    slots: ['PortfolioRiskMetricsSlot', 'RiskContributionSlot', 'RiskLimitChecksSlot'],
    layout: 'grid',
    defaultProps: {
      interactivity: {
        enableFiltering: true,
        enableDrillDown: true,
        enableCrossSlotCommunication: true
      }
    },
    generatePrompt: (portfolioData) => `Full risk dashboard with metrics, contributions, and limit checks for ${portfolioData.portfolio_name}`
  },
  
  // Interactive optimization artifacts
  portfolio_optimizer: {
    name: "Portfolio Optimizer",
    slots: ['PositionAnalysisSlot', 'IndustryContributionsSlot'],
    layout: 'optimization',
    defaultProps: {
      interactivity: {
        enableWeightAdjustment: true,
        enableRealTimeCalculation: true,
        enableScenarioComparison: true
      }
    },
    generatePrompt: (portfolioData) => `Interactive portfolio optimization with real-time risk and return calculations`
  }
};
```

---

## Type-Safe Data Flow Architecture

### **Pydantic as Single Source of Truth**

#### **Auto-Generated TypeScript Strategy**
Instead of maintaining separate Pydantic and TypeScript type definitions, we'll use **auto-generation** to ensure type consistency across the full stack.

```bash
# Install pydantic-to-typescript
pip install pydantic-to-typescript

# Generate TypeScript from Pydantic models
pydantic2ts --module models --output frontend/src/types/generated.ts
```

#### **Enhanced Pydantic Models for Chat + Artifacts**
```python
# models/chat_models.py
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Literal, Any
from datetime import datetime

class ChatMessage(BaseModel):
    """Chat message with artifact support"""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime
    artifacts: Optional[List["ArtifactSpec"]] = Field(default=None, description="Generated artifacts")
    function_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="Function execution results")

class ChatResponse(BaseModel):
    """Enhanced chat response with artifacts"""
    success: bool
    claude_response: Optional[str] = Field(default=None, description="Claude's text response")
    artifacts: List["ArtifactSpec"] = Field(default_factory=list, description="Interactive visualizations")
    function_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Executed functions")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    context_provided: Optional[Dict[str, Any]] = Field(default=None, description="Context metadata")

class ArtifactSpec(BaseModel):
    """Specification for Claude-generated interactive artifacts"""
    artifact_type: Literal["risk_dashboard", "allocation_analyzer", "performance_tracker", "optimization_tool", "scenario_comparison"]
    component_code: str = Field(..., description="React component code for artifact")
    data: Dict[str, Any] = Field(..., description="Portfolio data for artifact")
    slots_used: List[str] = Field(..., description="Chart slots included in artifact")
    interactivity: List[str] = Field(default_factory=list, description="Interactive features enabled")
    layout: Literal["single", "grid", "split", "tabs", "comparison"] = Field(default="grid")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Generation metadata")

class SlotInteraction(BaseModel):
    """User interaction with artifact slots"""
    type: Literal["data_filtered", "stock_drill_down", "weight_changed", "scenario_selected", "cross_slot_update"]
    source: str = Field(..., description="Source slot identifier")
    data: Dict[str, Any] = Field(..., description="Interaction data payload")
    description: str = Field(..., description="Human-readable interaction description")
    triggers_chat_response: bool = Field(default=False, description="Whether to send context to Claude")
    target_slots: Optional[List[str]] = Field(default=None, description="Slots to update from this interaction")

# models/portfolio_models.py - Enhanced for artifacts
class RiskAnalysisResult(BaseModel):
    """Enhanced risk analysis with artifact support"""
    risk_score: float = Field(..., ge=0, le=100, description="Portfolio risk score 0-100")
    risk_factors: Dict[str, float] = Field(..., description="Risk factor contributions")
    portfolio_metrics: "PortfolioMetrics"
    variance_decomposition: "VarianceBreakdown"
    # NEW: Artifact-specific data
    chart_data: Optional[Dict[str, Any]] = Field(default=None, description="Pre-formatted chart data")
    interactive_elements: Optional[List[str]] = Field(default=None, description="Available interactive features")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Decimal: float
        }

class PortfolioOptimizationResult(BaseModel):
    """Optimization results with artifact visualization support"""
    optimized_weights: Dict[str, float]
    expected_return: float
    expected_risk: float
    sharpe_ratio: float
    # NEW: Comparison data for artifacts
    current_vs_optimized: Optional[Dict[str, Any]] = Field(default=None, description="Before/after comparison")
    optimization_path: Optional[List[Dict[str, float]]] = Field(default=None, description="Optimization steps for visualization")
```

#### **Build Process Integration**
```json
// package.json - Enhanced scripts
{
  "scripts": {
    "generate-types": "python scripts/generate_types.py && prettier --write frontend/src/types/generated.ts",
    "generate-types:watch": "nodemon --watch '../models/**/*.py' --exec 'npm run generate-types'",
    "build": "npm run generate-types && npm run build:react",
    "dev": "concurrently \"npm run generate-types:watch\" \"npm run start\"",
    "type-check": "tsc --noEmit && python scripts/validate_schemas.py"
  },
  "devDependencies": {
    "concurrently": "^8.0.0",
    "nodemon": "^3.0.0"
  }
}
```

```python
# scripts/generate_types.py
#!/usr/bin/env python3
"""
Generate TypeScript definitions from Pydantic models
Ensures type consistency between backend and frontend
"""
import sys
import os
from pathlib import Path
from pydantic2ts import generate_typescript_defs

def main():
    """Generate TypeScript from all Pydantic models"""
    
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    try:
        # Generate TypeScript from all model modules
        typescript_content = generate_typescript_defs(
            "models.chat_models",
            "models.portfolio_models", 
            "models.artifact_models",
            output_file=None  # Return as string
        )
        
        # Add header with generation info
        header = f"""// AUTO-GENERATED - DO NOT EDIT
// Generated from Pydantic models at {datetime.now().isoformat()}
// To regenerate: npm run generate-types

/* eslint-disable */
// @ts-nocheck

"""
        
        # Output path
        output_path = project_root / "frontend" / "src" / "types" / "generated.ts"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write generated types
        with open(output_path, "w") as f:
            f.write(header)
            f.write(typescript_content)
            
        print(f"✅ Generated TypeScript types: {output_path}")
        
        # Also generate JSON schemas for runtime validation
        generate_json_schemas()
        
    except Exception as e:
        print(f"❌ Type generation failed: {e}")
        sys.exit(1)

def generate_json_schemas():
    """Generate JSON schemas for runtime validation"""
    from models.chat_models import ChatMessage, ChatResponse, ArtifactSpec, SlotInteraction
    from models.portfolio_models import RiskAnalysisResult, PortfolioOptimizationResult
    
    schemas = {
        "ChatMessage": ChatMessage.schema(),
        "ChatResponse": ChatResponse.schema(),
        "ArtifactSpec": ArtifactSpec.schema(),
        "SlotInteraction": SlotInteraction.schema(),
        "RiskAnalysisResult": RiskAnalysisResult.schema(),
        "PortfolioOptimizationResult": PortfolioOptimizationResult.schema()
    }
    
    schema_path = Path(__file__).parent.parent / "frontend" / "src" / "schemas" / "generated.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    
    import json
    with open(schema_path, "w") as f:
        json.dump(schemas, f, indent=2)
        
    print(f"✅ Generated JSON schemas: {schema_path}")

if __name__ == "__main__":
    main()
```

### **Type-Safe Frontend Integration**

#### **Auto-Generated Types Usage**
```typescript
// frontend/src/types/generated.ts (AUTO-GENERATED)
export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  artifacts?: ArtifactSpec[] | null;
  function_calls?: Record<string, any>[] | null;
}

export interface ChatResponse {
  success: boolean;
  claude_response?: string | null;
  artifacts: ArtifactSpec[];
  function_calls: Record<string, any>[];
  error?: string | null;
  context_provided?: Record<string, any> | null;
}

export interface ArtifactSpec {
  artifact_type: "risk_dashboard" | "allocation_analyzer" | "performance_tracker" | "optimization_tool" | "scenario_comparison";
  component_code: string;
  data: Record<string, any>;
  slots_used: string[];
  interactivity: string[];
  layout: "single" | "grid" | "split" | "tabs" | "comparison";
  metadata?: Record<string, any> | null;
}

export interface SlotInteraction {
  type: "data_filtered" | "stock_drill_down" | "weight_changed" | "scenario_selected" | "cross_slot_update";
  source: string;
  data: Record<string, any>;
  description: string;
  triggers_chat_response: boolean;
  target_slots?: string[] | null;
}
```

#### **Type-Safe Chat Service**
```typescript
// frontend/src/services/ClaudeService.ts - Enhanced with generated types
import { ChatMessage, ChatResponse, SlotInteraction, ArtifactSpec } from '../types/generated';
import { validateApiResponse } from '../utils/validation';

export class ClaudeService {
  // Type-safe chat with artifacts
  async sendMessageWithArtifacts(
    message: string,
    history: ChatMessage[],
    portfolioId: string
  ): Promise<ChatResponse> {
    try {
      const response = await this.request<ChatResponse>('/api/claude_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_message: message,
          chat_history: history,
          portfolio_id: portfolioId
        })
      });

      // Runtime validation against generated schema
      return validateApiResponse<ChatResponse>(response, 'ChatResponse');
      
    } catch (error) {
      // Type-safe error handling
      return {
        success: false,
        claude_response: null,
        artifacts: [],
        function_calls: [],
        error: error instanceof Error ? error.message : 'Unknown error',
        context_provided: null
      };
    }
  }

  // Type-safe slot interaction handling
  async handleSlotInteraction(interaction: SlotInteraction): Promise<ChatResponse | null> {
    if (!interaction.triggers_chat_response) {
      return null;
    }

    return this.sendMessageWithArtifacts(
      `Based on artifact interaction: ${interaction.description}`,
      [],
      this.currentPortfolioId
    );
  }
}
```

#### **Type-Safe Slot Enhancement**
```typescript
// frontend/src/components/dashboard/shared/charts/slots/RiskContributionSlot.tsx
import React, { useState, useCallback } from 'react';
import { SlotInteraction } from '../../../../../types/generated';

interface EnhancedSlotProps {
  // Existing props...
  factorData: any;
  loading?: boolean;
  error?: string | null;
  
  // NEW: Type-safe artifact props
  mode?: 'dashboard' | 'artifact';
  onSlotInteraction?: (interaction: SlotInteraction) => void;
  artifactContext?: {
    portfolioAPI: any;
    slotId: string;
  };
}

export const RiskContributionSlot: React.FC<EnhancedSlotProps> = ({
  factorData,
  mode = 'dashboard',
  onSlotInteraction,
  artifactContext,
  ...props
}) => {
  
  const handleStockClick = useCallback((stockData: any) => {
    if (mode === 'artifact' && onSlotInteraction) {
      // Type-safe interaction object
      const interaction: SlotInteraction = {
        type: 'stock_drill_down',
        source: artifactContext?.slotId || 'RiskContributionSlot',
        data: {
          ticker: stockData.ticker,
          risk_contribution: stockData.riskContribution,
          action: 'selected'
        },
        description: `Selected ${stockData.ticker} for detailed analysis`,
        triggers_chat_response: true,
        target_slots: null
      };
      
      onSlotInteraction(interaction);
    }
  }, [mode, onSlotInteraction, artifactContext]);

  // Rest of component...
};
```

#### **Runtime Validation**
```typescript
// frontend/src/utils/validation.ts
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import schemas from '../schemas/generated.json';

// Setup AJV with generated schemas
const ajv = new Ajv({ allErrors: true });
addFormats(ajv);

// Add all generated schemas
Object.entries(schemas).forEach(([name, schema]) => {
  ajv.addSchema(schema, name);
});

// Type-safe validation function
export const validateApiResponse = <T>(
  data: unknown,
  schemaName: string
): T => {
  const validate = ajv.getSchema(schemaName);
  
  if (!validate) {
    throw new Error(`Schema ${schemaName} not found`);
  }
  
  if (!validate(data)) {
    const errors = validate.errors?.map(err => 
      `${err.instancePath}: ${err.message}`
    ).join(', ');
    throw new Error(`Validation failed: ${errors}`);
  }
  
  return data as T;
};

// Artifact-specific validation
export const validateArtifactData = (artifact: unknown): ArtifactSpec => {
  return validateApiResponse<ArtifactSpec>(artifact, 'ArtifactSpec');
};
```

### **Development Workflow**

#### **Type Generation Workflow**
```bash
# 1. Developer modifies Pydantic models
# 2. Auto-regeneration triggers (via nodemon)
# 3. TypeScript types update automatically
# 4. Frontend gets immediate type safety

# Manual generation
npm run generate-types

# Watch mode during development  
npm run dev  # Includes type watching

# Validation
npm run type-check  # Validates both TS and Python types
```

#### **Pre-commit Hooks**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: generate-types
        name: Generate TypeScript types
        entry: npm run generate-types
        language: system
        files: models/.*\.py$
        pass_filenames: false
        
      - id: type-check
        name: Type check frontend and backend
        entry: npm run type-check
        language: system
        pass_filenames: false
```

---

## Backend Extensions

### **Enhanced Claude Service**

#### **Minimal Extensions to Existing Service**
```python
# Extend existing ClaudeChatService with artifact generation
class ClaudeChatService:
    def __init__(self):
        # Existing initialization (unchanged)
        self.client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.function_executor = ClaudeFunctionExecutor()
        self.portfolio_service = PortfolioContextService()
        
        # NEW: Artifact generation capability
        self.artifact_generator = SlotBasedArtifactGenerator()
    
    def _prepare_function_tools(self, available_functions):
        # Existing function tools (unchanged)
        base_tools = [{
            "name": func["name"],
            "description": func["description"],
            "input_schema": func["input_schema"]
        } for func in available_functions]
        
        # NEW: Add artifact generation tools
        artifact_tools = [
            {
                "name": "create_interactive_visualization",
                "description": "Create an interactive React component using existing chart slots",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "artifact_type": {
                            "type": "string",
                            "enum": ["risk_dashboard", "allocation_analyzer", "performance_tracker", "optimization_tool", "scenario_comparison"]
                        },
                        "data_source": {
                            "type": "string", 
                            "description": "Which portfolio function to call for data (e.g., 'run_portfolio_analysis', 'get_risk_score')"
                        },
                        "slots_requested": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific chart slots to include (e.g., ['RiskContributionSlot', 'PortfolioRiskMetricsSlot'])"
                        },
                        "interactivity": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Interactive features to enable (e.g., ['filtering', 'drill_down', 'weight_adjustment'])"
                        },
                        "layout": {
                            "type": "string",
                            "enum": ["single", "grid", "split", "tabs", "comparison"],
                            "description": "How to arrange multiple slots"
                        }
                    },
                    "required": ["artifact_type", "data_source"]
                }
            }
        ]
        
        return base_tools + artifact_tools
    
    # NEW: Enhanced process_chat with artifact support
    def process_chat(self, user_message, chat_history, user_key, user_tier, user=None, portfolio_name="CURRENT_PORTFOLIO"):
        """Enhanced chat processing with artifact generation capability"""
        try:
            # Existing chat processing (unchanged)...
            # [All existing logic remains the same]
            
            # NEW: Process artifact creation requests
            artifact_functions = [fc for fc in function_results if fc["function"] == "create_interactive_visualization"]
            
            artifacts = []
            for artifact_func in artifact_functions:
                if artifact_func["result"].get("success"):
                    artifact = self.artifact_generator.generate_slot_based_artifact(
                        artifact_spec=artifact_func["parameters"],
                        portfolio_data=portfolio_context
                    )
                    artifacts.append(artifact)
            
            # Return enhanced response with artifacts
            return {
                "success": True,
                "claude_response": claude_response,
                "function_calls": function_results,
                "artifacts": artifacts,  # NEW: Artifact data
                "context_provided": {
                    "risk_score": risk_score_value,
                    "analysis_length": len(portfolio_context['formatted_analysis']),
                    "functions_available": len(portfolio_context['available_functions']),
                    "artifacts_created": len(artifacts)  # NEW
                }
            }
            
        except Exception as e:
            return self._handle_chat_error(e, user_key, user_tier)
```

#### **Slot-Based Artifact Generator**
```python
class SlotBasedArtifactGenerator:
    """Generates React artifacts using existing chart slots"""
    
    def __init__(self):
        self.slot_templates = {
            "risk_dashboard": {
                "slots": ["PortfolioRiskMetricsSlot", "RiskContributionSlot", "RiskLimitChecksSlot"],
                "layout": "grid",
                "default_interactivity": ["filtering", "drill_down"]
            },
            "allocation_analyzer": {
                "slots": ["PositionAnalysisSlot", "IndustryContributionsSlot"],
                "layout": "split", 
                "default_interactivity": ["weight_adjustment", "real_time_calculation"]
            },
            "performance_tracker": {
                "slots": ["PerformanceBenchmarkSlot", "VarianceDecompositionSlot"],
                "layout": "vertical",
                "default_interactivity": ["time_range_selection", "benchmark_comparison"]
            }
        }
    
    def generate_slot_based_artifact(self, artifact_spec: dict, portfolio_data: dict) -> dict:
        """Generate artifact using existing chart slots"""
        
        artifact_type = artifact_spec.get("artifact_type")
        data_source = artifact_spec.get("data_source") 
        slots_requested = artifact_spec.get("slots_requested")
        interactivity = artifact_spec.get("interactivity", [])
        layout = artifact_spec.get("layout", "grid")
        
        # Use template or custom slot configuration
        if artifact_type in self.slot_templates:
            template = self.slot_templates[artifact_type]
            slots = slots_requested or template["slots"]
            layout = layout or template["layout"]
            interactivity = interactivity or template["default_interactivity"]
        else:
            slots = slots_requested or ["RiskContributionSlot"]  # Default fallback
        
        # Get data using existing function executor
        try:
            data_result = self.function_executor.execute_function(data_source, {})
            if not data_result.get('success'):
                return {"error": f"Failed to fetch data from {data_source}"}
            
            portfolio_data = data_result['result']
        except Exception as e:
            return {"error": f"Data source error: {str(e)}"}
        
        # Generate React component code
        component_code = self._generate_component_code(
            slots=slots,
            layout=layout,
            interactivity=interactivity,
            artifact_type=artifact_type
        )
        
        return {
            "type": "artifact",
            "artifact_type": artifact_type,
            "component_code": component_code,
            "data": portfolio_data,
            "slots_used": slots,
            "layout": layout,
            "interactivity": interactivity,
            "metadata": {
                "data_source": data_source,
                "generated_at": datetime.now(UTC).isoformat(),
                "portfolio_context": portfolio_data.get("portfolio_name", "Unknown")
            }
        }
    
    def _generate_component_code(self, slots: list, layout: str, interactivity: list, artifact_type: str) -> str:
        """Generate React component code using existing slots"""
        
        # Component imports
        imports = f"""
import React, {{ useState, useCallback, useMemo }} from 'react';
import {{ {', '.join(slots)} }} from './charts/slots';
"""
        
        # Interactive features setup
        interactivity_features = self._generate_interactivity_code(interactivity)
        
        # Layout-specific rendering
        layout_render = self._generate_layout_code(slots, layout)
        
        # Complete component
        component_name = f"{artifact_type.replace('_', ' ').title().replace(' ', '')}Artifact"
        
        return f"""{imports}

const {component_name} = ({{ portfolioData, portfolioAPI }}) => {{
{interactivity_features}

  return (
    <div className="artifact-container artifact-{layout}">
{layout_render}
    </div>
  );
}};

export default {component_name};
"""
    
    def _generate_interactivity_code(self, interactivity: list) -> str:
        """Generate interactive state and handlers"""
        if not interactivity:
            return "  // No interactive features enabled"
        
        code_parts = []
        
        if "filtering" in interactivity:
            code_parts.append("""
  const [filters, setFilters] = useState({});
  
  const handleFilterChange = useCallback((slotId, filterData) => {
    setFilters(prev => ({ ...prev, [slotId]: filterData }));
  }, []);""")
        
        if "drill_down" in interactivity:
            code_parts.append("""
  const [selectedItems, setSelectedItems] = useState([]);
  
  const handleItemSelection = useCallback((item) => {
    setSelectedItems(prev => 
      prev.includes(item.id) 
        ? prev.filter(id => id !== item.id)
        : [...prev, item.id]
    );
  }, []);""")
        
        if "weight_adjustment" in interactivity:
            code_parts.append("""
  const [adjustedWeights, setAdjustedWeights] = useState({});
  
  const handleWeightChange = useCallback((ticker, newWeight) => {
    setAdjustedWeights(prev => ({ ...prev, [ticker]: newWeight }));
    
    // Trigger real-time recalculation
    portfolioAPI.calculateRisk({ ...portfolioData.weights, [ticker]: newWeight })
      .then(newRiskData => {
        // Update dependent slots
      });
  }, [portfolioData, portfolioAPI]);""")
        
        return "\n".join(code_parts)
    
    def _generate_layout_code(self, slots: list, layout: str) -> str:
        """Generate layout-specific rendering code"""
        
        slot_components = []
        for i, slot in enumerate(slots):
            slot_props = f"""
        factorData={{portfolioData}}
        mode="artifact"
        interactivity={{{{
          enableFiltering: true,
          enableDrillDown: true,
          onDataChange: (interaction) => handleSlotInteraction('{slot}', interaction)
        }}}}
        artifactContext={{{{ portfolioAPI }}}}"""
            
            slot_components.append(f"""      <{slot}{slot_props}
      />""")
        
        if layout == "grid":
            grid_class = f"grid-cols-{min(len(slots), 2)}" if len(slots) > 1 else "grid-cols-1"
            return f"""      <div className="grid {grid_class} gap-4">
{chr(10).join(slot_components)}
      </div>"""
        
        elif layout == "split":
            return f"""      <div className="flex gap-4">
{chr(10).join(slot_components)}
      </div>"""
        
        elif layout == "vertical":
            return f"""      <div className="space-y-4">
{chr(10).join(slot_components)}
      </div>"""
        
        elif layout == "tabs":
            tab_content = []
            for i, (slot, component) in enumerate(zip(slots, slot_components)):
                tab_content.append(f"""        {{activeTab === {i} && (
{component}
        )}}""")
            
            return f"""      <div className="tabs-container">
        <div className="tab-buttons">
          {chr(10).join([f'<button onClick={() => setActiveTab({i})}>{slot.replace("Slot", "")}</button>' for i, slot in enumerate(slots)])}
        </div>
        <div className="tab-content">
{chr(10).join(tab_content)}
        </div>
      </div>"""
        
        else:  # single or default
            return f"""      <div className="single-slot-container">
{slot_components[0] if slot_components else '        <div>No slots configured</div>'}
      </div>"""
```

---

## Implementation Strategy

### **Strategic Implementation Approach**

Our implementation follows the **Four Strategic Value Pillars**, building AI-native intelligence into every component from day one:

1. **Phase 0**: Foundation Stabilization with Type Safety
2. **Phase 1**: AI-Native Foundation + **Pillar 1** (Intent-Aware Intelligence)
3. **Phase 2**: **Pillar 3** (Real-Time What-If Intelligence) via interactive artifacts  
4. **Phase 3**: **Pillar 2** (Proactive Decision Support) with monitoring
5. **Phase 4**: **Pillar 4** (Contextual Learning & Adaptation) for personalization

### **Phase 0: Foundation Stabilization with Type Safety (Week 1)**

#### **Strategic Focus: Solve Data Flow Issues with New Architecture Foundation**
Fix existing frontend-backend wiring issues by implementing the type generation system from the new architecture. This solves current problems while laying the groundwork for AI features.

#### **Critical Understanding**
Current data mismatch issues between frontend and backend are exactly what the auto-generated TypeScript system is designed to solve. Rather than manually fixing data inconsistencies, implement the type-safe foundation that eliminates these issues automatically.

#### **Type System Implementation**
1. **Install pydantic-to-typescript**: `pip install pydantic-to-typescript`
2. **Create type generation script** (`scripts/generate_types.py`):
   ```python
   #!/usr/bin/env python3
   """Generate TypeScript definitions from Pydantic models"""
   import sys
   from pathlib import Path
   from pydantic2ts import generate_typescript_defs
   from datetime import datetime

   def main():
       """Generate TypeScript from existing Pydantic models"""
       project_root = Path(__file__).parent.parent
       sys.path.insert(0, str(project_root))
       
       try:
           # Generate from your existing models
           typescript_content = generate_typescript_defs(
               "models.portfolio_models",    # Your existing portfolio models
               "models.risk_models",         # Your existing risk models  
               "models.user_models",         # Your existing user models
               output_file=None
           )
           
           # Header with generation info
           header = f"""// AUTO-GENERATED - DO NOT EDIT
// Generated from Pydantic models at {datetime.now().isoformat()}
// To regenerate: npm run generate-types

/* eslint-disable */
// @ts-nocheck

"""
           
           # Output to frontend
           output_path = project_root / "frontend" / "src" / "types" / "generated.ts"
           output_path.parent.mkdir(parents=True, exist_ok=True)
           
           with open(output_path, "w") as f:
               f.write(header + typescript_content)
               
           print(f"✅ Generated TypeScript types: {output_path}")
           
       except Exception as e:
           print(f"❌ Type generation failed: {e}")
           sys.exit(1)

   if __name__ == "__main__":
       main()
   ```

3. **Update package.json** with type generation scripts:
   ```json
   {
     "scripts": {
       "generate-types": "python scripts/generate_types.py && prettier --write frontend/src/types/generated.ts",
       "generate-types:watch": "nodemon --watch '../models/**/*.py' --exec 'npm run generate-types'",
       "build": "npm run generate-types && npm run build:react",
       "dev": "concurrently \"npm run generate-types:watch\" \"npm run start\"",
       "type-check": "tsc --noEmit"
     }
   }
   ```

#### **Chart Slot Foundation**
1. **Select 2-3 core chart slots** for initial wiring (e.g., RiskContributionSlot, PortfolioRiskMetricsSlot)
2. **Add mode prop** to existing slots for future artifact compatibility:
   ```typescript
   interface SlotProps {
     // Existing props (unchanged)
     factorData: any;
     loading?: boolean;
     error?: string | null;
     
     // NEW: Future artifact support
     mode?: 'dashboard' | 'artifact';
   }
   ```

3. **Wire selected slots** to backend using generated types:
   ```typescript
   // Import auto-generated types
   import { RiskAnalysisResult, PortfolioMetrics } from '../types/generated';
   
   // Type-safe API calls
   const riskData = await api.getRiskAnalysis(portfolioId) as RiskAnalysisResult;
   ```

#### **API Endpoint Completion**
1. **Audit missing API endpoints** needed for selected chart slots
2. **Implement 2-3 critical endpoints** using existing Pydantic models
3. **Test type-safe data flow** from Pydantic → generated TypeScript → React slots
4. **Validate real portfolio data** flows correctly through the type-safe pipeline

#### **Success Criteria for Phase 0**
- ✅ Type generation system working and auto-updating on model changes
- ✅ 2-3 chart slots fully functional with real backend data
- ✅ Zero TypeScript errors in data flow from backend to frontend
- ✅ Existing dashboard functionality preserved and improved
- ✅ Foundation ready for AI architecture implementation

#### **Phase 0 Deliverables**
1. **Working type generation system** that eliminates data mismatch issues
2. **2-3 fully functional chart slots** with type-safe backend integration
3. **Validated data architecture** proving Pydantic → TypeScript → React flow
4. **Updated build process** with automatic type generation
5. **Documentation** of type-safe development workflow

### **Phase 1: AI-Native Foundation + Intent-Aware Intelligence (Week 2-3)**

#### **Strategic Focus: Pillar 1 - Intent-Aware Financial Intelligence**
Build the foundation for understanding WHY users are asking, not just WHAT they're asking.

#### **Type System Setup**
1. **Install pydantic-to-typescript**: `pip install pydantic-to-typescript`
2. **Create enhanced Pydantic models** with AI context support:
   - `models/chat_models.py` - ChatResponse, ArtifactSpec, SlotInteraction
   - `models/intent_models.py` - UserIntent, ContextualRequest, AIGuidance
   - `models/intelligence_models.py` - UserPatterns, MarketContext, ProactiveAlert
3. **Set up type generation script** (`scripts/generate_types.py`)
4. **Configure build process** with auto-generation and watch mode
5. **Add runtime validation** with AJV and generated schemas

#### **Intent-Aware Backend Setup**
1. **Create Intent Detection Service**:
   ```python
   class IntentDetectionService:
       def analyze_user_intent(self, message, user_context, portfolio_context):
           # Detect user goals, concerns, urgency, timeline
           return UserIntent(...)
   ```

2. **Enhance ClaudeChatService** with intent-aware context:
   ```python
   class ClaudeChatService:
       def process_chat_with_intent(self, user_message, chat_history, user_context):
           # Detect intent first
           intent = self.intent_service.analyze_user_intent(...)
           
           # Build rich context
           enhanced_context = self.build_contextual_request(intent, portfolio_data, market_data)
           
           # Process with Claude using enhanced context
           return self.claude_client.messages.create(...)
   ```

3. **Add Market Context Integration**:
   ```python
   class MarketContextService:
       def get_current_market_context(self):
           # Economic indicators, market volatility, sector trends
           return MarketContext(...)
   ```

#### **Intent-Aware Frontend Setup**
1. **Add ArtifactProvider** to existing provider hierarchy
2. **Create ChatPanel** with intent detection:
   ```typescript
   const ChatPanel = () => {
     const detectUserIntent = (message) => {
       // Frontend intent hints for better UX
       return analyzeMessageForIntent(message, userContext);
     };
     
     const sendIntentAwareMessage = async (message) => {
       const intent = detectUserIntent(message);
       return claudeService.sendMessageWithIntent(message, intent, chatHistory);
     };
   };
   ```

3. **Extend AppOrchestrator** with intelligent interface switching
4. **Add contextual intent guidance** system
5. **Enhance ClaudeService** with intent-aware methods

#### **Slot Enhancement for AI Integration**
1. **Add `mode` prop** with AI context support:
   ```typescript
   interface AIEnhancedSlotProps {
     mode?: 'dashboard' | 'artifact';
     aiGuidance?: AIGuidance;              // NEW: AI explanations
     onSlotInteraction?: (interaction: SlotInteraction) => void;
     intentContext?: UserIntent;           // NEW: Why user is viewing this
   }
   ```

2. **Keep existing dashboard behavior** as default
3. **Add AI-guided interactivity** for artifact mode
4. **Test dual-purpose slots** with intent awareness

### **Phase 2: Real-Time What-If Intelligence (Week 4-5)**

#### **Strategic Focus: Pillar 3 - Real-Time What-If Intelligence**
Enable instant scenario exploration with AI guidance that explains what the numbers mean.

#### **AI-Guided Artifact Execution**
1. **Implement ArtifactSandbox** with AI interpretation capability:
   ```typescript
   class AIGuidedArtifactSandbox {
     async executeWithGuidance(artifact: ArtifactSpec, userIntent: UserIntent) {
       const executedArtifact = await this.execute(artifact);
       
       // NEW: Add AI guidance layer
       const aiGuidance = await this.claudeService.generateArtifactGuidance({
         artifact_type: artifact.artifact_type,
         user_intent: userIntent,
         initial_data: artifact.data
       });
       
       return { artifact: executedArtifact, guidance: aiGuidance };
     }
   }
   ```

2. **Create SecurePortfolioProxy** with real-time calculation hooks
3. **Add AI-interpreted artifact rendering** to chat interface
4. **Test scenario exploration** with AI explanations

#### **Real-Time Scenario Intelligence**
1. **Enhance slot interactivity** with AI interpretation:
   ```typescript
   const ScenarioExplorationSlot = ({ onScenarioChange, aiContext }) => {
     const handleUserChange = async (changes) => {
       // Real-time calculation (existing)
       const results = await portfolioAPI.calculateScenario(changes);
       
       // NEW: AI interpretation of results
       const aiInsight = await claudeService.interpretScenarioResults({
         changes,
         results,
         user_context: aiContext.userIntent,
         previous_scenarios: scenarioHistory
       });
       
       onScenarioChange({ results, aiGuidance: aiInsight });
     };
   };
   ```

2. **Implement real-time AI guidance** for user interactions
3. **Add scenario comparison** with AI-powered insights
4. **Create template scenarios** for common user goals

#### **Intelligent Chat-Artifact Integration**
1. **Add bidirectional communication** between chat and artifacts:
   ```typescript
   // User changes something in artifact → AI explains impact
   const handleArtifactInteraction = async (interaction: SlotInteraction) => {
     if (interaction.triggers_chat_response) {
       const aiResponse = await claudeService.interpretUserAction({
         interaction,
         current_portfolio_state: portfolioContext,
         user_intent: intentContext
       });
       
       addChatMessage({
         role: 'assistant',
         content: aiResponse.explanation,
         context: aiResponse.suggested_next_steps
       });
     }
   };
   ```

2. **Implement contextual guidance** system
3. **Add scenario suggestion** based on user behavior
4. **Test complete what-if exploration flows**

### **Phase 3: Proactive Decision Support (Week 6-7)**

#### **Strategic Focus: Pillar 2 - Proactive Decision Support**  
Anticipate what users need before they ask, with AI-powered monitoring and alerts.

#### **Intelligent Portfolio Monitoring**
1. **Create ProactiveIntelligenceEngine**:
   ```python
   class ProactiveIntelligenceEngine:
       def __init__(self):
           self.portfolio_monitor = YourExistingRiskAnalysis()
           self.claude_ai = ClaudeChatService()
           self.alert_generator = ProactiveAlertService()
       
       async def monitor_and_alert(self, user_id):
           # Analyze current state
           portfolio_state = await self.portfolio_monitor.analyze_comprehensive(user_id)
           
           # Detect emerging concerns
           concerns = self.detect_emerging_issues(portfolio_state, user_context)
           
           if concerns:
               # Generate AI-powered proactive insights
               alert = await self.claude_ai.generate_proactive_guidance({
                   concerns: concerns,
                   user_context: user_context,
                   suggested_actions: self.get_suggested_actions(concerns)
               })
               
               return ProactiveAlert(
                   alert_type=concerns.primary_concern,
                   ai_analysis=alert,
                   suggested_artifacts=concerns.suggested_visualizations,
                   urgency=concerns.urgency_level
               )
   ```

2. **Add background monitoring** with intelligent thresholds
3. **Implement notification system** with AI-generated insights
4. **Create alert management** interface

#### **Context-Aware Alerting**
1. **Add market event correlation** to portfolio alerts
2. **Implement user preference learning** for alert timing
3. **Create intelligent alert grouping** and prioritization
4. **Add proactive scenario generation** for detected issues

#### **Advanced User Experience**
1. **Polish chat interface** with proactive suggestions
2. **Add intelligent artifact management** (auto-arrange, smart suggestions)
3. **Implement alert-driven workflows** 
4. **Add mobile-optimized proactive alerts**

### **Phase 4: Contextual Learning & Adaptation (Week 8-9)**

#### **Strategic Focus: Pillar 4 - Contextual Learning & Adaptation**
System learns user patterns and adapts over time, becoming more helpful like a personal advisor.

#### **User Intelligence System**
1. **Create UserIntelligenceService**:
   ```python
   class UserIntelligenceService:
       def __init__(self):
           self.pattern_analyzer = UserPatternAnalyzer()
           self.preference_engine = PreferenceEngine()
           self.adaptation_engine = AdaptationEngine()
       
       def enhance_all_interactions(self, user_id, interaction_request):
           # Learn from user behavior patterns
           patterns = self.pattern_analyzer.analyze_decision_patterns(user_id)
           preferences = self.preference_engine.get_learned_preferences(user_id)
           
           # Adapt communication and recommendations
           return self.adaptation_engine.personalize_experience(
               request=interaction_request,
               user_patterns=patterns,
               preferences=preferences
           )
   ```

2. **Add behavioral pattern analysis** for decision making
3. **Implement preference learning** for communication style
4. **Create adaptive recommendation engine**

#### **Personalized AI Experience** 
1. **Add learning-enhanced Claude interactions**
2. **Implement adaptive artifact suggestions**
3. **Create personalized risk communication**
4. **Add intelligent workflow suggestions**

#### **Advanced Integration & Testing**
1. **End-to-end AI-native user flows**
2. **Performance optimization** for AI-enhanced features
3. **Security testing** for learning systems
4. **Cross-platform AI experience testing**

---

## User Experience Design

### **Interface Layouts**

#### **Chat + Artifacts Layout**
```
┌─────────────────────────────────────────────────────────────────┐
│ Portfolio Risk Analysis - Chat + Artifacts Mode                │
├─────────────────────────────────────────────────────────────────┤
│ [📊 Dashboard] [💬 Chat + Artifacts] [⚙️ Settings]            │
├─────────────────────┬───────────────────────────────────────────┤
│                     │                                           │
│ 💬 CHAT PANEL       │ 📊 ACTIVE ARTIFACTS                      │
│                     │                                           │
│ ┌─ Context ─────┐   │ ┌─ Risk Dashboard ──────────────────────┐ │
│ │ Portfolio:     │   │ │ 🛡️ Risk Score: 73                   │ │
│ │ CURRENT        │   │ │ ┌──────┬──────┬──────┐               │ │
│ │ Risk: 73       │   │ │ │ Risk │ Cont │ Lmts │ [Interactive] │ │
│ │ Last: 2m ago   │   │ │ │ Mtrx │ Anal │ Chck │               │ │
│ └───────────────┘   │ │ └──────┴──────┴──────┘               │ │
│                     │ │ [Filter] [Drill Down] [Adjust]       │ │
│ ┌─ Quick Actions ┐   │ └───────────────────────────────────────┘ │
│ │🛡️ Reduce Risk  │   │                                           │
│ │📈 Optimize     │   │ ┌─ Allocation Optimizer ──────────────┐ │
│ │⚖️ Rebalance    │   │ │ Drag sliders to test allocations:    │ │
│ │🔍 Analyze      │   │ │ AAPL: ████████ 25% → 20%            │ │
│ └───────────────┘   │ │ MSFT: ██████ 20% → 25%               │ │
│                     │ │ New Risk Score: 73 → 68 ✅           │ │
│ User: "Show me     │   │ │ [Apply Changes] [Reset] [Save]       │ │
│ my risk dashboard"  │   │ └───────────────────────────────────────┘ │
│                     │                                           │
│ Claude: "Here's    │   │ [+ Add Artifact] [⚙️ Arrange]        │
│ your interactive    │   │                                           │
│ risk dashboard..."  │   │                                           │
│                     │                                           │
│ ┌─────────────────┐ │                                           │
│ │ Type message... │ │                                           │
│ └─────────────────┘ │                                           │
└─────────────────────┴───────────────────────────────────────────┘
```

### **User Flow Examples**

#### **Flow 1: Risk Analysis**
```
1. User: "Show me my portfolio risk breakdown"
   → Claude: Creates risk dashboard artifact
   → Artifact displays: Risk score + interactive charts
   
2. User: Clicks on high-risk stock in artifact
   → Artifact: Highlights stock, sends context to Claude
   → Claude: "I see you clicked on TSLA (15% risk contribution)..."
   
3. User: "How can I reduce this risk?"
   → Claude: Runs what-if scenarios, updates artifact
   → Artifact: Shows before/after with interactive sliders
```

#### **Flow 2: Portfolio Optimization**
```
1. User: "Help me optimize my portfolio"
   → Claude: Creates optimization artifact + runs analysis
   → Artifact: Shows current vs optimized allocations
   
2. User: Adjusts allocation sliders in artifact
   → Artifact: Real-time risk/return calculation
   → Claude: "Your changes improve the Sharpe ratio from 1.2 to 1.4..."
   
3. User: "What if tech crashes 30%?"
   → Claude: Runs stress test, updates artifact
   → Artifact: Shows portfolio impact with scenario sliders
```

### **Intent Recognition Patterns**

#### **Risk-Related Intents**
```typescript
const riskIntents = {
  "reduce risk": "🛡️ Show risk analysis + suggest risk reduction strategies",
  "too risky": "🚨 Analyze current risk factors + create risk dashboard",
  "stress test": "📉 Create stress testing artifact with scenario sliders",
  "what if crash": "💥 Generate market crash simulation artifact"
};
```

#### **Optimization Intents**
```typescript
const optimizationIntents = {
  "optimize portfolio": "⚡ Create optimization artifact with strategy comparison",
  "better returns": "📈 Run return optimization + show return/risk trade-offs",
  "rebalance": "⚖️ Generate rebalancing artifact with target allocations",
  "diversify": "🌐 Create diversification analysis + suggestions"
};
```

---

## Security & Sandboxing

### **Artifact Security Architecture**

#### **Multi-Layer Security**
```typescript
class ArtifactSecurity {
  // Layer 1: Code Validation
  validateComponentCode(code: string): SecurityValidation {
    const dangerousPatterns = [
      /fetch\(/g,           // Prevent network calls
      /XMLHttpRequest/g,    // Prevent AJAX
      /eval\(/g,            // Prevent code execution
      /Function\(/g,        // Prevent dynamic function creation
      /import\(/g,          // Prevent dynamic imports
      /require\(/g,         // Prevent module loading
      /localStorage/g,      // Prevent storage access
      /sessionStorage/g,    // Prevent storage access
      /document\./g,        // Prevent DOM manipulation outside sandbox
      /window\./g,          // Prevent window object access
    ];
    
    for (const pattern of dangerousPatterns) {
      if (pattern.test(code)) {
        return { 
          safe: false, 
          violation: `Dangerous pattern detected: ${pattern}`,
          blocked: true 
        };
      }
    }
    
    return { safe: true, blocked: false };
  }
  
  // Layer 2: Runtime Isolation
  createIsolatedContext(portfolioService: PortfolioService) {
    return {
      // Safe React hooks
      React, useState, useEffect, useMemo, useCallback,
      
      // Safe libraries
      recharts: { PieChart, BarChart, LineChart, ResponsiveContainer },
      lodash: { pick, omit, groupBy, sortBy }, // Limited lodash
      
      // Controlled portfolio API
      portfolioAPI: new SecurePortfolioProxy(portfolioService),
      
      // No access to:
      // - fetch, XMLHttpRequest
      // - localStorage, sessionStorage  
      // - document, window
      // - eval, Function
      // - Node.js modules
    };
  }
  
  // Layer 3: API Access Control
  createSecurePortfolioProxy(portfolioService: PortfolioService): SecurePortfolioProxy {
    return {
      // ALLOW: Safe read operations
      getCurrentPortfolio: () => portfolioService.getCurrentPortfolio(),
      getRiskAnalysis: () => portfolioService.getRiskAnalysis(),
      runScenario: (weights) => this.validateAndExecute(
        () => portfolioService.runWhatIfScenario(weights),
        { maxExecutionTime: 5000, rateLimitPerMinute: 10 }
      ),
      
      // BLOCK: Dangerous operations
      savePortfolio: () => { throw new SecurityError('Write operations not allowed'); },
      deletePortfolio: () => { throw new SecurityError('Delete operations not allowed'); },
      updateUserSettings: () => { throw new SecurityError('Settings changes not allowed'); },
      
      // RATE LIMITED: Expensive operations
      optimizePortfolio: this.rateLimit(
        (params) => portfolioService.optimizePortfolio(params),
        { maxCallsPerMinute: 3 }
      )
    };
  }
}
```

#### **Runtime Monitoring**
```typescript
class ArtifactRuntime {
  private executionLimits = {
    maxMemoryMB: 50,
    maxExecutionTimeMs: 10000,
    maxAPICallsPerMinute: 20,
    maxComponentDepth: 10
  };
  
  executeArtifact(componentCode: string, context: IsolatedContext): Promise<ReactComponent> {
    return new Promise((resolve, reject) => {
      // Set execution timeout
      const timeout = setTimeout(() => {
        reject(new ArtifactTimeoutError('Artifact execution exceeded time limit'));
      }, this.executionLimits.maxExecutionTimeMs);
      
      try {
        // Monitor memory usage
        const memoryBefore = performance.memory?.usedJSHeapSize || 0;
        
        // Execute in isolated context
        const component = this.renderInIsolation(componentCode, context);
        
        const memoryAfter = performance.memory?.usedJSHeapSize || 0;
        const memoryUsed = (memoryAfter - memoryBefore) / (1024 * 1024); // MB
        
        if (memoryUsed > this.executionLimits.maxMemoryMB) {
          reject(new ArtifactMemoryError(`Memory usage ${memoryUsed}MB exceeds limit`));
          return;
        }
        
        clearTimeout(timeout);
        resolve(component);
        
      } catch (error) {
        clearTimeout(timeout);
        reject(new ArtifactExecutionError(`Execution failed: ${error.message}`));
      }
    });
  }
}
```

### **User Data Protection**

#### **Portfolio Data Isolation**
```typescript
// Ensure artifacts only access user's own data
class UserDataIsolation {
  validateDataAccess(user: AuthenticatedUser, portfolioId: string): boolean {
    // Verify user owns the portfolio
    if (!user.portfolios.includes(portfolioId)) {
      throw new UnauthorizedAccessError('Access to portfolio denied');
    }
    
    // Verify session is valid
    if (!this.validateSession(user.sessionId)) {
      throw new SessionExpiredError('Session expired');
    }
    
    return true;
  }
  
  sanitizePortfolioData(rawData: any, user: AuthenticatedUser): any {
    // Remove sensitive information
    const sanitized = { ...rawData };
    delete sanitized.internalIds;
    delete sanitized.databaseMetadata;
    delete sanitized.auditTrail;
    
    // Ensure user-specific data only
    sanitized.userId = user.id;
    sanitized.accessLevel = user.tier;
    
    return sanitized;
  }
}
```

---

## Migration Plan

### **Rollout Strategy**

#### **Phase 1: Internal Testing (Week 1-2)**
- **Target**: Development team only
- **Scope**: Basic chat interface + simple artifacts
- **Goal**: Validate architecture and identify issues
- **Success Criteria**: 
  - Chat interface works alongside existing dashboard
  - Basic artifacts render and execute safely
  - No impact on existing dashboard functionality

#### **Phase 2: Beta Testing (Week 3-4)**  
- **Target**: 10-20 selected power users
- **Scope**: Full chat + artifacts functionality
- **Goal**: User feedback and refinement
- **Success Criteria**:
  - Users can complete common tasks via chat
  - Artifacts provide value over static dashboards
  - Performance meets expectations

#### **Phase 3: Gradual Rollout (Week 5-6)**
- **Target**: All users with feature flag
- **Scope**: Chat + artifacts as optional interface
- **Goal**: Monitor adoption and stability
- **Success Criteria**:
  - <1% error rate in chat/artifact system
  - Positive user engagement metrics
  - No regression in dashboard usage

#### **Phase 4: Full Deployment (Week 7+)**
- **Target**: All users by default
- **Scope**: Chat + artifacts as primary interface option
- **Goal**: Complete migration to dual-interface system
- **Success Criteria**:
  - Users actively choose between interfaces
  - Support tickets reduced due to better user guidance
  - Increased user engagement and satisfaction

### **Rollback Strategy**

#### **Feature Flags**
```typescript
// Granular feature control
const featureFlags = {
  chat_interface_enabled: true,
  artifact_execution_enabled: true,
  advanced_interactivity_enabled: false,
  experimental_artifacts_enabled: false
};

// Gradual enablement by user tier
const tierBasedRollout = {
  paid: featureFlags,
  registered: { ...featureFlags, advanced_interactivity_enabled: false },
  public: { chat_interface_enabled: false, artifact_execution_enabled: false }
};
```

#### **Monitoring & Alerts**
```typescript
// Real-time monitoring
const criticalMetrics = {
  artifact_execution_failure_rate: { threshold: 0.05, alert: 'immediate' },
  chat_response_time: { threshold: 8000, alert: 'warning' },
  memory_usage_per_artifact: { threshold: 100, alert: 'warning' },
  security_violations: { threshold: 1, alert: 'immediate' }
};

// Automatic rollback triggers
const autoRollback = {
  artifact_failure_rate_5min: 0.20,  // 20% failure rate → disable artifacts
  memory_leak_detection: true,        // Memory growth → restart sandboxes
  security_violation: true            // Any security issue → immediate disable
};
```

### **Training & Documentation**

#### **User Education**
1. **Interactive Tutorials**: Guided tours of chat + artifact features
2. **Video Demonstrations**: Common use cases and workflows
3. **Help Documentation**: Comprehensive user guides
4. **In-App Guidance**: Contextual tips and suggestions

#### **Developer Documentation**
1. **Architecture Guide**: Complete system documentation
2. **Slot Development**: How to create artifact-compatible slots
3. **Security Guidelines**: Artifact development best practices
4. **Troubleshooting**: Common issues and solutions

---

## Conclusion

This architecture design provides a comprehensive roadmap for integrating Claude Chat + Interactive Artifacts into the existing portfolio risk analysis platform. The design prioritizes:

### **Key Strengths**

✅ **Leverages Existing Architecture**: Minimal changes to proven, sophisticated system
✅ **Progressive Enhancement**: Can be implemented in phases without breaking changes
✅ **Dual-Purpose Components**: Chart slots work seamlessly in both contexts
✅ **Type-Safe Data Flow**: Auto-generated TypeScript ensures frontend/backend consistency
✅ **Security-First**: Multi-layer security with comprehensive sandboxing
✅ **User-Centric**: Natural language interface with intelligent context awareness
✅ **Developer Experience**: Full type safety with auto-completion and runtime validation

### **Expected Outcomes**

#### **Strategic Value Delivery**
- **AI-Native Portfolio Intelligence**: First platform designed with AI at the core, not retrofitted
- **Intent-Aware Decision Support**: AI that understands WHY users are asking, not just WHAT
- **Proactive Financial Guidance**: Anticipates user needs before they become problems
- **Personalized Learning Experience**: System adapts to individual user patterns over time

#### **User Experience Transformation**
- **From Analysis Paralysis to Guided Action**: AI copilot transforms raw data into actionable insights
- **From Periodic Check-ins to Continuous Intelligence**: 24/7 AI advisor vs quarterly meetings
- **From Static Reports to Interactive Exploration**: Real-time scenario testing with AI guidance
- **From Generic Tools to Personal Financial Intelligence**: Adapts to individual decision patterns

#### **Technical Excellence**
- **Type-Safe AI Integration**: Full-stack type safety from Pydantic to React artifacts
- **Scalable Intelligence Architecture**: Foundation for millions of users with personalized AI
- **Security-First AI Execution**: Multi-layer security for artifact execution and user data
- **Progressive Enhancement**: Existing dashboard preserved while adding AI capabilities

### **Next Steps**

1. **Stakeholder Review**: Review architecture with team and gather feedback
2. **Proof of Concept**: Build minimal viable implementation (Phase 1)
3. **User Testing**: Validate concept with target users
4. **Implementation Planning**: Detailed sprint planning and resource allocation

This design transforms the platform from a traditional dashboard into an **AI-native portfolio intelligence platform** - the first of its kind built from the ground up with AI at the core. 

**The Strategic Opportunity**: We're not adding AI to an existing tool; we're building the first financial platform designed with AI intelligence as the foundation. This creates a fundamentally different and more valuable user experience that competitors can't easily replicate.

**The Competitive Moat**: Our sophisticated risk analysis + AI integration + modern artifacts creates compound value that deepens over time as the system learns user patterns and market contexts. This combination of technical sophistication and AI-native design establishes a strong competitive position in the portfolio intelligence market.