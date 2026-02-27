# Asset Class System Design

**Status**: Design document - asset class system is NOT IMPLEMENTED. Current system treats all assets as equities with basic ticker support.

## Overview
Replace the current equity-only factor model with a proper asset class system that applies appropriate risk constraints based on asset type.

## Asset Class Categories

### 1. **Equity**
- **Description**: Common stocks and equity ETFs
- **Risk Factors**: Market, Momentum, Value, Industry, Idiosyncratic
- **Constraints**: Industry beta limits, concentration limits, sector diversification
- **Examples**: NVDA, AAPL, XLK, SPY

### 2. **Government Bonds** 
- **Description**: Treasury bills, notes, bonds, and government bond ETFs
- **Risk Factors**: Duration, Credit (minimal), Interest Rate
- **Constraints**: Duration limits, no industry beta constraints
- **Examples**: SGOV, SHY, IEF, TLT

### 3. **Corporate Bonds**
- **Description**: Corporate bonds and corporate bond ETFs
- **Risk Factors**: Duration, Credit Spread, Interest Rate
- **Constraints**: Duration limits, credit quality limits
- **Examples**: LQD, HYG, JNK

### 4. **Commodities**
- **Description**: Physical commodities and commodity ETFs
- **Risk Factors**: Commodity-specific factors, inflation hedge
- **Constraints**: Commodity concentration limits
- **Examples**: SLV, GLD, USO, DJP

### 5. **Real Estate**
- **Description**: REITs and real estate ETFs (treated separately from equities)
- **Risk Factors**: Real estate factors, interest rate sensitivity
- **Constraints**: Real estate concentration limits
- **Examples**: VNQ, XLRE, individual REITs

### 6. **Alternative Investments**
- **Description**: Private equity, hedge funds, structured products
- **Risk Factors**: Alternative-specific factors
- **Constraints**: Alternative investment limits
- **Examples**: TIPS, commodity futures, structured notes

## Current Portfolio Categorization

| Asset | Current Treatment | Proposed Asset Class | Rationale |
|-------|------------------|---------------------|-----------|
| SGOV  | Equity (industry: SGOV) | Government Bonds | Treasury bill ETF |
| DSU   | Equity (industry: DSU) | Equity | Utility company stock |
| EQT   | Equity (industry: XOP) | Equity | Energy company stock |
| IGIC  | Equity (industry: KIE) | Equity | Insurance company stock |
| IT    | Equity (industry: XLK) | Equity | Technology company stock |
| KINS  | Equity (industry: KIE) | Equity | Insurance company stock |
| MSCI  | Equity (industry: KCE) | Equity | Financial services stock |
| NVDA  | Equity (industry: SOXX) | Equity | Technology company stock |
| RNMBY | Equity (industry: ITA) | Equity | Defense company stock |
| SFM   | Equity (industry: XLP) | Equity | Consumer staples stock |
| SLV   | Equity (industry: SLV) | Commodities | Silver ETF |
| STWD  | Equity (industry: REM) | Equity | Real estate company stock |
| TKO   | Equity (industry: XLC) | Equity | Media/entertainment stock |
| V     | Equity (industry: KCE) | Equity | Financial services stock |

## Implementation Plan

### Phase 1: Portfolio Structure Update
- Add `asset_class` field to portfolio.yaml
- Categorize all current assets
- Maintain backward compatibility

### Phase 2: Factor Computation Updates
- Modify factor computation to be asset-class-aware
- Only apply industry constraints to equities
- Add asset-class-specific risk calculations

### Phase 3: Constraint Logic Updates
- Create asset-class-specific constraint functions
- Update optimization functions to use appropriate constraints
- Add validation for asset class constraints

### Phase 4: Risk Reporting Updates
- Show asset-class-specific risk metrics
- Add asset class diversification reporting
- Update risk summaries to be asset-class-aware

## Benefits
1. **Proper Risk Management**: Each asset class gets appropriate risk constraints
2. **Eliminates Current Bugs**: No more impossible industry beta constraints for bonds
3. **Extensible**: Easy to add new asset classes in the future
4. **Industry Standard**: Aligns with how institutional investors manage risk
5. **Better Diversification**: Can monitor diversification across asset classes

## Backward Compatibility
- Existing portfolio.yaml files will continue to work
- New asset_class field will be optional initially
- Gradual migration path for existing portfolios 