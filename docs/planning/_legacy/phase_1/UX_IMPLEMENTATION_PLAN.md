# UX Implementation Plan

## Overview
This document tracks planned UX improvements for the Risk Module frontend. Each improvement is documented with current behavior, desired behavior, and implementation details.

## Implementation Items

### 1. Auto-Load Portfolio on Page Load ✅ Priority: High

**Current Behavior:**
- User loads page → Empty/no portfolio shown
- User must click refresh → Fetches from Plaid → Shows portfolio

**Desired Behavior:**
- User loads page → Automatically load and display saved "CURRENT_PORTFOLIO" from database
- Portfolio displays immediately if user has existing data
- Refresh button remains available for manual updates

**Implementation Details:**

**VALIDATED: Existing Infrastructure**
- ✅ **Endpoint exists**: `GET /api/portfolios/<portfolio_name>` at `routes/api.py:997`
- ✅ **Authentication**: Uses `get_current_user()` which checks session cookie
- ✅ **Portfolio loading**: Uses `PortfolioManager` to load from database
- ⚠️ **Data format mismatch**: Endpoint returns different format than Plaid

**Backend Requirements:**

1. **Fix Existing Endpoint** at `routes/api.py:1018`:
   ```python
   # Current line has error - PortfolioData doesn't have to_dict()
   'portfolio_data': portfolio_data.to_dict()  # This will fail
   
   # Should be:
   from dataclasses import asdict
   'portfolio_data': asdict(portfolio_data)
   ```

2. **Create Transform Function** to match Plaid format:
   ```python
   def transform_portfolio_for_display(portfolio_data):
       """Transform PortfolioData to match Plaid display format"""
       holdings_list = []
       total_value = 0
       
       for ticker, holding in portfolio_data.standardized_input.items():
           if "shares" in holding:
               # Need to fetch price to calculate market_value
               # This is where real-time pricing comes in (Issue #4)
               holdings_list.append({
                   "ticker": ticker,
                   "shares": holding["shares"],
                   "market_value": 0,  # Placeholder until pricing implemented
                   "security_name": ""  # Would need lookup
               })
           elif "dollars" in holding:
               holdings_list.append({
                   "ticker": ticker,
                   "shares": holding["dollars"],
                   "market_value": holding["dollars"],
                   "security_name": "Cash"
               })
       
       return {
           "holdings": holdings_list,
           "total_portfolio_value": total_value,
           "statement_date": portfolio_data._last_updated,
           "account_type": "Database Portfolio"
       }
   ```

**Frontend Implementation:**

1. **On Component Mount**:
   ```javascript
   useEffect(() => {
       loadPortfolioFromDatabase();
   }, []);
   
   const loadPortfolioFromDatabase = async () => {
       try {
           setLoading(true);
           const response = await fetch('/api/portfolios/CURRENT_PORTFOLIO', {
               credentials: 'include'  // Important for session auth
           });
           
           if (response.ok) {
               const data = await response.json();
               // Transform if needed or use directly
               displayPortfolio(data.portfolio_data);
           } else if (response.status === 404) {
               // No portfolio exists yet
               showEmptyState();
           }
       } catch (error) {
           console.error('Failed to load portfolio:', error);
       } finally {
           setLoading(false);
       }
   };
   ```

2. **Authentication Handling**:
   - Session cookie must be included with request
   - Handle 401 response by redirecting to login
   - Backend uses session to identify user

**Key Findings:**
- Portfolio name must be exactly "CURRENT_PORTFOLIO"
- Session-based auth via cookies (no user_id in request)
- Data format transformation needed between backend and frontend
- Must handle case where no portfolio exists (404 response)

---

### 2. Add Last Updated Timestamp ✅ Priority: High

**Current Behavior:**
- No indication of when portfolio data was last synced
- Users don't know if they're viewing fresh or stale data

**Desired Behavior:**
- Display "Updated X hours ago" to the left of the refresh button
- Use relative time format (e.g., "2 hours ago", "3 days ago", "Just now")

**Implementation Details:**
1. Extract `last_updated` timestamp from portfolio data
   - Field available in PortfolioData object: `portfolio_data._last_updated`
2. Format as relative time using a library like:
   - moment.js with `fromNow()` function
   - or date-fns `formatDistanceToNow()` function
3. Position to the left of refresh button
4. Style with muted color (e.g., gray text) to be informative but not distracting

**UI Example:**
```
Last updated 2 hours ago  [🔄 Refresh]
```

---

### 3. Remove Redundant "Analyze Risk" Button ✅ Priority: High

**Current Behavior:**
- "Analyze Risk" button appears next to "Refresh" button
- Button is not connected to any functionality
- Creates confusion for users (two buttons, unclear difference)

**Desired Behavior:**
- Remove the "Analyze Risk" button entirely
- Keep only the "Refresh" button for updating portfolio data
- Cleaner, simpler UI with clear actions

**Implementation Details:**

**VALIDATED: Button Location & Functionality**
- ✅ **Found button**: `/frontend/src/components/portfolio/PlaidPortfolioHoldings.tsx` lines 51-53
- ✅ **No onClick handler**: Button has no functionality attached
- ✅ **No props passed**: Parent component doesn't pass any analyze-related props
- ✅ **Safe to remove**: No other components depend on this button

**Specific Code Changes:**

1. **Remove button from PlaidPortfolioHoldings.tsx**:
   
   **File**: `frontend/src/components/portfolio/PlaidPortfolioHoldings.tsx`
   
   **Current code (lines 33-54):**
   ```tsx
   <div className="flex space-x-3">
     <button
       onClick={onRefresh}
       disabled={refreshLoading}
       className="text-gray-600 hover:text-gray-800 underline text-sm disabled:opacity-50"
     >
       {refreshLoading ? (
         <span className="flex items-center">
           <svg className="animate-spin -ml-1 mr-2 h-3 w-3 text-gray-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
             <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
             <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
           </svg>
           Refreshing...
         </span>
       ) : (
         'Refresh'
       )}
     </button>
     <button className="bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-4 rounded">
       Analyze Risk
     </button>
   </div>
   ```
   
   **New code (remove lines 51-53 and adjust wrapper):**
   ```tsx
   <div>
     <button
       onClick={onRefresh}
       disabled={refreshLoading}
       className="text-gray-600 hover:text-gray-800 underline text-sm disabled:opacity-50"
     >
       {refreshLoading ? (
         <span className="flex items-center">
           <svg className="animate-spin -ml-1 mr-2 h-3 w-3 text-gray-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
             <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
             <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
           </svg>
           Refreshing...
         </span>
       ) : (
         'Refresh'
       )}
     </button>
   </div>
   ```

2. **Layout adjustments**:
   - Remove `flex space-x-3` class from wrapper div since only one button remains
   - No other layout changes needed as the refresh button will align to the right

**Verification Checklist:**
- No event handlers attached to the button ✓
- No props for analyze functionality ✓
- No CSS classes used elsewhere ✓
- No state management for this button ✓
- Parent component (App.tsx) doesn't expect analyze functionality ✓

**Testing Notes:**
- Test that refresh button still works after removal
- Verify layout looks correct with single button
- Check responsive behavior on mobile

**Rationale:**
- Risk analysis happens automatically when portfolio is loaded/refreshed
- Button literally does nothing when clicked (no onClick handler)
- Having two buttons creates confusion about what each does
- Simplifies the UI to have one clear action

---

### 4. Real-Time Price Updates for Portfolio Display ✅ Priority: High

**Current Behavior:**
- Portfolio loads with saved market values from when it was last synced with Plaid
- Values are stale (from `institution_value` field in Plaid data)
- Users see outdated portfolio values

**Desired Behavior:**
- Portfolio loads positions (shares/quantities) from database
- Frontend automatically fetches current prices for all tickers
- Market values calculated fresh: shares × current_price
- Display shows real-time portfolio value on page load

**Implementation Details:**

**Backend Changes:**

1. **Add New Method to Existing PortfolioService** in `services/portfolio_service.py`:
```python
def refresh_portfolio_prices(self, portfolio_data: PortfolioData) -> Dict[str, Any]:
    """
    Refresh portfolio with current market prices.
    Returns updated holdings with current values.
    """
    from run_portfolio_risk import latest_price
    
    updated_holdings = []
    total_value = 0
    
    for ticker, holding in portfolio_data.standardized_input.items():
        if ticker.startswith("CUR:"):  # Cash position
            # Cash always has price of 1.0
            value = holding.get("dollars", 0)
            updated_holdings.append({
                "ticker": ticker,
                "shares": value,
                "market_value": value,
                "security_name": "Cash"
            })
            total_value += value
        else:  # Equity position
            shares = holding.get("shares", 0)
            current_price = latest_price(ticker)
            market_value = shares * current_price
            
            updated_holdings.append({
                "ticker": ticker,
                "shares": shares,
                "market_value": market_value,
                "security_name": ""  # Would need lookup or store from Plaid
            })
            total_value += market_value
    
    return {
        "holdings": updated_holdings,
        "total_portfolio_value": total_value,
        "prices_updated_at": datetime.now().isoformat()
    }
```

2. **Create New API Endpoint** in `routes/api.py`:
   - Endpoint: `GET /api/portfolio/refresh-prices`
   - Load user's CURRENT_PORTFOLIO from database
   - Call service method to refresh prices
   - Return updated holdings with fresh market values

**Frontend Changes:**

1. **Add Price Refresh on Portfolio Load**:
   - After loading portfolio from database, immediately call refresh-prices endpoint
   - Update display with fresh values
   - Show loading state while fetching prices

2. **Update UI to Show Dual Timestamps**:
   - "Holdings last synced: [Plaid sync time]"
   - "Prices as of: [current time]"
   - Both timestamps visible to user

**Technical Architecture:**
```
Current Flow:
Database → Portfolio (shares + old values) → Display

New Flow:
Database → Portfolio (shares) → Fetch Prices API → Calculate Values → Display
```

**Key Implementation Points:**

- **Reuse Existing Infrastructure**:
  - `latest_price()` function at `run_portfolio_risk.py:203`
  - FMP API integration with caching in `data_loader.py`
  - Cache stored in `cache_prices/` directory

- **Handle Different Position Types**:
  - Equity: Fetch price from FMP API
  - Cash: Price always 1.0
  - Error handling: Fall back to cached values

- **Performance Considerations**:
  - Leverage existing cache system
  - Show loading states
  - Graceful degradation on API failures

**Testing Requirements:**
- Test with various portfolio compositions
- Verify cash positions handled correctly
- Test fallback behavior on API failures
- Performance testing for large portfolios

---

## Implementation Order

### Recommended Sequence

Based on technical dependencies and complexity, implement in this order:

**1. Remove "Analyze Risk" Button (Item #3)** ⚡ Quick Win
- **Why First**: Independent, no dependencies, simple deletion
- **Time Estimate**: 15 minutes
- **Risk**: Very low - no functionality attached
- **Benefit**: Immediate UI cleanup

**2. Auto-Load Portfolio (Item #1)** 🔄 Core Feature  
- **Dependencies**: None (can use placeholder prices initially)
- **Why Second**: Foundation for other features, high user value
- **Time Estimate**: 2-3 hours (including bug fix)
- **Key Tasks**:
  - Fix the `to_dict()` bug in backend
  - Implement data transformation
  - Add frontend auto-load logic

**3. Real-Time Price Updates (Item #4)** 💹 Enhancement
- **Dependencies**: Enhances Item #1 (provides actual prices)
- **Why Third**: Completes the auto-load feature with live data
- **Time Estimate**: 3-4 hours
- **Key Tasks**:
  - Create price refresh service method
  - Add new API endpoint
  - Update frontend to fetch prices

**4. Add Last Updated Timestamp (Item #2)** 🕐 Polish
- **Dependencies**: Needs Item #1 (to have something to timestamp)
- **Why Last**: UI polish that requires portfolio data
- **Time Estimate**: 1 hour
- **Key Tasks**:
  - Extract timestamp from portfolio
  - Add relative time formatting
  - Position in UI

### Dependency Graph
```
Item #3 (Remove Button) → Independent
         ↓
Item #1 (Auto-Load) → Provides portfolio data
         ↓                    ↓
Item #4 (Prices)      Item #2 (Timestamp)
    Enhanced by            Depends on
```

### Alternative Approaches

**Parallel Implementation** (if multiple developers):
- Developer 1: Item #3, then Item #1
- Developer 2: Start Item #4 (can develop service layer in parallel)
- Merge and complete Item #2 together

**Minimal MVP**:
- Just implement Items #3 and #1 first
- Deploy and gather user feedback
- Add Items #4 and #2 in next iteration

---

## Future Improvements (To Be Defined)

### 5. [Next UX Improvement - TBD]

**Current Behavior:**
- 

**Desired Behavior:**
- 

**Implementation Details:**
- 

---

## Notes for Implementers

1. **API Endpoints**: Verify existing endpoints support these features or document new endpoints needed
2. **Error Handling**: Ensure graceful fallbacks if data loading fails
3. **Testing**: Test with both new users (no portfolio) and existing users (with saved portfolio)
4. **Session Management**: All API calls should include proper authentication via session cookies

## Version History

- v1.0 (2025-07-22): Initial document with portfolio auto-load and timestamp display
- v1.1 (2025-07-22): Added removal of redundant "Analyze Risk" button
- v1.2 (2025-07-22): Added real-time price updates with comprehensive implementation details
- v1.3 (2025-07-22): Validated and updated auto-load implementation with specific code fixes needed
- v1.4 (2025-07-22): Validated Analyze Risk button removal with exact code location and changes
- v1.5 (2025-07-22): Added implementation order section and clarified timestamp field access and price refresh implementation
- v1.6 (2025-07-22): Clarified that refresh_portfolio_prices should be added to existing PortfolioService class