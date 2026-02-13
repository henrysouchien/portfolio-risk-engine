# Frontend Refactoring Plan

## Overview

Transform the current 1,476-line `App.js` monolith into a maintainable, scalable React architecture that separates data/business logic from presentation components. This refactoring will enable rapid UI iteration and design system development.

## Strategic Goals

- **Enable rapid UX/UI iteration**: Break down monolithic App.js to allow fast design changes
- **Separate concerns**: Create clean separation between data/business logic and presentation
- **Maintain functionality**: Keep all existing features working throughout refactoring
- **Production readiness**: Ensure refactored code is production-ready with proper error handling

## Architecture Decisions

### **Chassis + Components Pattern**
- **Chassis**: Handles all data, business logic, API calls, and state management
- **Components**: Pure presentation components that receive clean data as props
- **Connection**: Custom hooks serve as the interface between chassis and components

### **Service Layer Strategy**
- **Option B (Chosen)**: Chassis managers call APIs directly (simpler approach)
- **No separate service layer**: Avoid over-engineering with extra abstraction layers

### **State Management Strategy**
- **Global State (React Context)**: User auth, current portfolio, Plaid connections
- **Local State (useState)**: AI chat messages, form inputs, UI state
- **AI-Optimized**: Simple streaming response handling, no complex state trees

### **Implementation Approach**
- **Full refactor**: Complete transformation rather than incremental changes
- **Phased testing**: Test each phase thoroughly before moving to next
- **Risk mitigation**: Backup original files, commit frequently, gradual migration

## Target Architecture

```
src/
├── chassis/
│   ├── managers/          # AuthManager, PortfolioManager, PlaidManager, ChatManager
│   ├── hooks/             # useAuth, usePortfolio, usePlaid, useChat
│   └── context/           # AppContext for global state
├── components/
│   ├── auth/              # Authentication UI
│   ├── portfolio/         # Portfolio display components
│   ├── plaid/             # Plaid integration UI
│   ├── chat/              # AI chat interface
│   ├── layouts/           # Page layouts
│   └── shared/            # Reusable UI components
└── App.js                 # High-level routing + providers
```

## Current State Analysis

- **1,476-line App.js** with all functionality in one file
- **Working React frontend** with Google Auth, Plaid integration, portfolio analysis, AI chat
- **Backend APIs ready** at `/api/portfolio/*`, `/api/claude_chat`, etc.
- **Need**: Refactor for maintainability and UI iteration speed

## Implementation Plan

### **Phase 1: Foundation**

**Objective**: Set up the basic architecture and folder structure

**Tasks**:
1. **Create folder structure**:
   ```
   src/
   ├── chassis/
   │   ├── managers/
   │   ├── hooks/
   │   └── context/
   ├── components/
   │   ├── auth/
   │   ├── portfolio/
   │   ├── plaid/
   │   ├── chat/
   │   ├── layouts/
   │   └── shared/
   ```

2. **Backup original App.js**:
   ```bash
   cp frontend/src/App.js frontend/src/App.original.js
   ```

3. **Create AppContext for global state**:
   ```javascript
   // chassis/context/AppContext.js
   const AppProvider = ({ children }) => {
     const [user, setUser] = useState(null);
     const [isAuthenticated, setIsAuthenticated] = useState(false);
     const [currentPortfolio, setCurrentPortfolio] = useState(null);
     const [portfolios, setPortfolios] = useState([]);
     const [plaidConnections, setPlaidConnections] = useState([]);
     
     return (
       <AppContext.Provider value={{
         user, setUser,
         isAuthenticated, setIsAuthenticated,
         currentPortfolio, setCurrentPortfolio,
         portfolios, setPortfolios,
         plaidConnections, setPlaidConnections
       }}>
         {children}
       </AppContext.Provider>
     );
   };
   ```

### **Phase 2: Chassis Managers**

**Objective**: Extract all business logic and API calls into manager classes

**Tasks**:
1. **Create AuthManager**:
   ```javascript
   // chassis/managers/AuthManager.js
   class AuthManager {
     async handleGoogleSignIn(credentialResponse) {
       // Extract Google sign-in logic from App.js
       // Make API calls to /api/auth/google
       // Return user data
     }
     
     async signOut() {
       // Handle sign out logic
     }
   }
   ```

2. **Create PortfolioManager**:
   ```javascript
   // chassis/managers/PortfolioManager.js  
   class PortfolioManager {
     async uploadPortfolio(file) {
       // Extract portfolio upload logic
       // Call /api/portfolio/upload
     }
     
     async analyzeRisk(portfolioData) {
       // Call /api/portfolio/analyze
     }
     
     async getRiskScore(portfolioId) {
       // Call /api/portfolio/risk_score
     }
   }
   ```

3. **Create PlaidManager**:
   ```javascript
   // chassis/managers/PlaidManager.js
   class PlaidManager {
     async createLinkToken() {
       // Call /api/plaid/create_link_token
     }
     
     async getHoldings() {
       // Call /api/plaid/holdings
     }
     
     async getConnectedAccounts() {
       // Call /api/plaid/accounts
     }
   }
   ```

4. **Create ChatManager**:
   ```javascript
   // chassis/managers/ChatManager.js
   class ChatManager {
     async sendMessage(message, context) {
       // Handle streaming responses from /api/claude_chat
       // Return streaming interface
     }
     
     async getSessionHistory() {
       // Get chat history for current session
     }
   }
   ```

### **Phase 3: Custom Hooks**

**Objective**: Create interface layer between chassis and components

**Tasks**:
1. **Create useAuth hook**:
   ```javascript
   // chassis/hooks/useAuth.js
   export const useAuth = () => {
     const context = useContext(AppContext);
     const authManager = new AuthManager();
     
     const signIn = async (credentialResponse) => {
       const user = await authManager.handleGoogleSignIn(credentialResponse);
       context.setUser(user);
       context.setIsAuthenticated(true);
     };
     
     const signOut = async () => {
       await authManager.signOut();
       context.setUser(null);
       context.setIsAuthenticated(false);
     };
     
     return { 
       signIn, 
       signOut, 
       user: context.user, 
       isAuthenticated: context.isAuthenticated 
     };
   };
   ```

2. **Create usePortfolio hook**:
   ```javascript
   // chassis/hooks/usePortfolio.js
   export const usePortfolio = () => {
     const context = useContext(AppContext);
     const portfolioManager = new PortfolioManager();
     const [loading, setLoading] = useState(false);
     const [error, setError] = useState(null);
     
     const uploadPortfolio = async (file) => {
       setLoading(true);
       try {
         const result = await portfolioManager.uploadPortfolio(file);
         context.setCurrentPortfolio(result);
         setLoading(false);
         return result;
       } catch (err) {
         setError(err.message);
         setLoading(false);
       }
     };
     
     const analyzeRisk = async (portfolioData) => {
       setLoading(true);
       try {
         const analysis = await portfolioManager.analyzeRisk(portfolioData);
         setLoading(false);
         return analysis;
       } catch (err) {
         setError(err.message);
         setLoading(false);
       }
     };
     
     return {
       uploadPortfolio,
       analyzeRisk,
       currentPortfolio: context.currentPortfolio,
       portfolios: context.portfolios,
       loading,
       error
     };
   };
   ```

3. **Create useChat hook with AI streaming**:
   ```javascript
   // chassis/hooks/useChat.js
   export const useChat = () => {
     const [messages, setMessages] = useState([]);
     const [isStreaming, setIsStreaming] = useState(false);
     const chatManager = new ChatManager();
     
     const sendMessage = async (message) => {
       // Add user message immediately (optimistic)
       setMessages(prev => [...prev, { role: 'user', content: message }]);
       
       // Start streaming AI response
       setIsStreaming(true);
       const response = await fetch('/api/claude_chat', {
         method: 'POST',
         body: JSON.stringify({ message }),
         headers: { 'Content-Type': 'application/json' }
       });
       
       // Handle streaming response
       const reader = response.body.getReader();
       let aiMessage = { role: 'assistant', content: '' };
       
       while (true) {
         const { done, value } = await reader.read();
         if (done) break;
         
         const chunk = new TextDecoder().decode(value);
         aiMessage.content += chunk;
         
         // Update messages with streaming content
         setMessages(prev => {
           const newMessages = [...prev];
           newMessages[newMessages.length - 1] = aiMessage;
           return newMessages;
         });
       }
       
       setIsStreaming(false);
     };
     
     return { messages, sendMessage, isStreaming };
   };
   ```

### **Phase 4: Component Extraction**

**Objective**: Extract UI components from App.js and connect to hooks

**Priority Order**:
1. **Authentication Components** (simplest, self-contained)
2. **Portfolio Display Components** (core functionality)
3. **Plaid Integration Components** (external API dependency)
4. **Chat Components** (most complex, streaming responses)

**Tasks**:
1. **Extract GoogleSignInButton**:
   ```javascript
   // components/auth/GoogleSignInButton.js
   const GoogleSignInButton = ({ onSuccess, onError }) => {
     // Extract Google sign-in button JSX from App.js
     // Use onSuccess/onError callbacks
     return (
       <GoogleLogin
         onSuccess={onSuccess}
         onError={onError}
       />
     );
   };
   ```

2. **Extract LandingPage**:
   ```javascript
   // components/auth/LandingPage.js
   const LandingPage = ({ onSignIn }) => {
     // Extract landing page UI + GoogleSignInButton
     // Props: onSignIn callback
     // State: None (stateless)
     return (
       <div className="landing-page">
         <h1>Portfolio Risk Analysis</h1>
         <GoogleSignInButton onSuccess={onSignIn} />
       </div>
     );
   };
   ```

3. **Extract RiskScoreDisplay**:
   ```javascript
   // components/portfolio/RiskScoreDisplay.js
   const RiskScoreDisplay = ({ riskScore, loading }) => {
     // Extract risk score display JSX from App.js
     // Pure presentation component
     if (loading) return <LoadingSpinner />;
     return (
       <div className="risk-score-card">
         <h3>Risk Score: {riskScore?.value}</h3>
         <RiskMeter value={riskScore?.value} />
         <RiskBreakdown breakdown={riskScore?.breakdown} />
       </div>
     );
   };
   ```

4. **Extract TabbedPortfolioAnalysis**:
   ```javascript
   // components/portfolio/TabbedPortfolioAnalysis.js
   const TabbedPortfolioAnalysis = ({ 
     portfolio, 
     onAnalyze, 
     analysisResults 
   }) => {
     // Extract tab switching, analysis display
     // Props: portfolio data, callbacks, results
     // State: activeTab, local UI state
     const [activeTab, setActiveTab] = useState('overview');
     
     return (
       <div className="tabbed-analysis">
         <TabNavigation activeTab={activeTab} onTabChange={setActiveTab} />
         <TabContent tab={activeTab} portfolio={portfolio} results={analysisResults} />
       </div>
     );
   };
   ```

5. **Extract RiskAnalysisChat**:
   ```javascript
   // components/chat/RiskAnalysisChat.js
   const RiskAnalysisChat = ({ 
     portfolio, 
     isAuthenticated 
   }) => {
     const { messages, sendMessage, isStreaming } = useChat();
     
     return (
       <div className="chat-interface">
         <ChatMessages messages={messages} />
         <ChatInput 
           onSendMessage={sendMessage} 
           disabled={isStreaming}
         />
       </div>
     );
   };
   ```

### **Phase 5: Integration & Polish**

**Objective**: Clean up App.js and add shared components

**Tasks**:
1. **Clean up App.js**:
   ```javascript
   // App.js (simplified)
   function App() {
     const { user, isAuthenticated } = useAuth();
     
     return (
       <AppProvider>
         <BrowserRouter>
           <Routes>
             <Route path="/" element={
               !isAuthenticated ? (
                 <LandingPage />
               ) : (
                 <DashboardLayout>
                   <DashboardPage />
                 </DashboardLayout>
               )
             } />
           </Routes>
         </BrowserRouter>
       </AppProvider>
     );
   }
   ```

2. **Add shared components**:
   ```javascript
   // components/shared/LoadingSpinner.js
   // components/shared/ErrorMessage.js  
   // components/shared/Modal.js
   // components/shared/Button.js
   ```

3. **Create layouts**:
   ```javascript
   // components/layouts/DashboardLayout.js
   const DashboardLayout = ({ children }) => {
     const { user, signOut } = useAuth();
     
     return (
       <div className="dashboard-layout">
         <Header user={user} onSignOut={signOut} />
         <Sidebar />
         <main className="main-content">
           {children}
         </main>
         <Footer />
       </div>
     );
   };
   ```

## Testing Strategy

### **Per-Component Testing**
1. Extract component to new file
2. Import in App.js (replace inline component)
3. Test functionality - should work identically
4. Commit change for rollback safety

### **Integration Testing**
1. Test auth flow - Google sign-in works
2. Test portfolio upload - file upload + analysis
3. Test Plaid integration - account connection
4. Test chat interface - AI responses work

### **Risk Mitigation**
- **Backup Strategy**: Keep original App.js as App.original.js
- **Commit frequently**: After each component extraction
- **Gradual migration**: Start with simplest components (auth)
- **Rollback plan**: Each component extraction is one commit

## Expected Outcomes

### **After Phase 1-2**:
- Foundation and chassis managers in place
- Data flow working correctly
- Business logic separated from presentation

### **After Phase 3-4**:
- Components organized into logical folders
- Same functionality, better maintainability
- Ready for rapid UX/UI iteration

### **After Phase 5**:
- Clean separation of concerns
- Reusable component library
- Foundation for design system

## Immediate Benefits

- **Faster development**: Find/edit components easily
- **Better testing**: Test components in isolation
- **Team collaboration**: Multiple people can work on different components
- **UX iteration**: Quick design changes without breaking functionality
- **Maintainability**: Clear separation between data and presentation
- **Scalability**: Easy to add new features and components

## Key Principles

1. **Components never call APIs directly** - Always go through hooks
2. **Hooks serve as interface** - Clean boundary between chassis and components
3. **Keep AI state simple** - Streaming responses work better with local state
4. **Maintain working app** - Never break existing functionality
5. **Test thoroughly** - Each phase must work before moving to next 