"""Provider protocols and registry for external market/FX data."""

from __future__ import annotations

from typing import Protocol, runtime_checkable, Optional, Union

import pandas as pd


@runtime_checkable
class PriceProvider(Protocol):
    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series: ...
    def fetch_monthly_treasury_rates(self, maturity: str, start_date=None, end_date=None) -> pd.Series: ...
    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame: ...
    def fetch_current_dividend_yield(self, ticker, **kw) -> float: ...


@runtime_checkable
class FXProvider(Protocol):
    def adjust_returns_for_fx(self, returns: pd.Series, currency: str, **kw) -> Union[pd.Series, dict]: ...
    def get_fx_rate(self, currency: str) -> float: ...


_price_provider: Optional[PriceProvider] = None
_fx_provider: Optional[FXProvider] = None


def set_price_provider(provider: PriceProvider) -> None:
    global _price_provider
    _price_provider = provider


def get_price_provider() -> PriceProvider:
    global _price_provider
    if _price_provider is None:
        from portfolio_risk_engine._fmp_provider import FMPPriceProvider

        _price_provider = FMPPriceProvider()
    return _price_provider


def set_fx_provider(provider: FXProvider) -> None:
    global _fx_provider
    _fx_provider = provider


def get_fx_provider() -> Optional[FXProvider]:
    return _fx_provider
