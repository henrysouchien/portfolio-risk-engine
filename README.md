# portfolio-risk-engine

Quantitative portfolio analytics library — factor regression, risk decomposition, optimization, and performance attribution.

## Install

```bash
pip install portfolio-risk-engine
```

## What it does

- **Factor analysis** — multi-factor regression with HAC standard errors, rolling betas, factor contribution decomposition
- **Risk decomposition** — systematic vs idiosyncratic risk, variance attribution by factor and position
- **Portfolio optimization** — mean-variance, minimum-variance, maximum-return with configurable constraints
- **Risk scoring** — composite risk score across concentration, volatility, factor exposure, and drawdown dimensions
- **Performance metrics** — Sharpe, Sortino, max drawdown, tracking error, information ratio, up/down capture
- **Income projection** — dividend yield forecasting with coverage and growth analysis
- **Scenario analysis** — what-if position changes with full risk recomputation

## Quick Start

```python
from portfolio_risk_engine import build_portfolio_view

result = build_portfolio_view(
    weights={"AAPL": 0.3, "MSFT": 0.3, "GOOGL": 0.2, "BND": 0.2},
)
```

## Data Providers

The engine uses a `PriceProvider` protocol for market data. A default FMP-backed provider is included when `fmp-mcp` is installed:

```python
from portfolio_risk_engine.providers import set_price_provider

# Use the built-in FMP provider (requires FMP_API_KEY env var)
from portfolio_risk_engine._fmp_provider import FMPPriceProvider
set_price_provider(FMPPriceProvider())

# Or bring your own:
from portfolio_risk_engine.providers import PriceProvider

class MyProvider(PriceProvider):
    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw): ...
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw): ...
    # ...
```

## License

MIT
