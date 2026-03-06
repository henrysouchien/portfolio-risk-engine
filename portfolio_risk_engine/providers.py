"""Provider protocols and registry for external market/FX data."""

from __future__ import annotations

from typing import Any, Optional, Protocol, Union, runtime_checkable

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
    def get_spot_fx_rate(self, currency: str) -> float: ...
    def get_monthly_fx_series(
        self,
        currency: str,
        start_date=None,
        end_date=None,
    ) -> pd.Series: ...
    def get_daily_fx_series(
        self,
        currency: str,
        start_date=None,
        end_date=None,
    ) -> pd.Series:
        return self.get_monthly_fx_series(currency, start_date, end_date)


@runtime_checkable
class CurrencyResolver(Protocol):
    def infer_currency(self, ticker: str) -> Optional[str]: ...


_price_provider: Optional[PriceProvider] = None
_fx_provider: Optional[FXProvider] = None
_currency_resolver: Optional[CurrencyResolver] = None


class _RegistryBackedPriceProvider:
    """Adapter that preserves the legacy PriceProvider interface via ProviderRegistry."""

    @staticmethod
    def _normalize_kwargs(ticker: str, kw: dict[str, Any]) -> dict[str, Any]:
        fmp_ticker_map = dict(kw.get("fmp_ticker_map") or {})
        fmp_ticker = kw.get("fmp_ticker")
        if fmp_ticker:
            fmp_ticker_map[ticker] = fmp_ticker
        return {
            "instrument_type": kw.get("instrument_type", "equity"),
            "contract_identity": kw.get("contract_identity"),
            "fmp_ticker_map": fmp_ticker_map or None,
        }

    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series:
        from providers.bootstrap import get_registry

        normalized = self._normalize_kwargs(str(ticker), kw)
        chain = get_registry().get_price_chain(normalized["instrument_type"])
        last_exc: Exception | None = None
        last_result: pd.Series | None = None

        for provider in chain:
            try:
                result = provider.fetch_monthly_close(
                    ticker,
                    start_date,
                    end_date,
                    **normalized,
                )
                if result is not None and not result.empty:
                    return result
                last_result = result
            except Exception as exc:
                last_exc = exc
                continue

        if last_result is not None:
            return last_result
        raise ValueError(f"No provider could price {ticker}") from last_exc

    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series:
        from providers.bootstrap import get_registry

        dividend_provider = get_registry().get_dividend_provider()
        if dividend_provider:
            return dividend_provider.fetch_monthly_total_return_price(
                ticker,
                start_date,
                end_date,
                **kw,
            )

        from utils.logging import portfolio_logger

        portfolio_logger.warning(
            "No DividendProvider registered - falling back to close-only for %s",
            ticker,
        )
        return self.fetch_monthly_close(ticker, start_date, end_date, **kw)

    def fetch_monthly_treasury_rates(self, maturity: str, start_date=None, end_date=None) -> pd.Series:
        from providers.bootstrap import get_registry

        treasury_provider = get_registry().get_treasury_provider()
        if treasury_provider:
            return treasury_provider.fetch_monthly_treasury_rates(maturity, start_date, end_date)
        raise ValueError("No treasury rate provider registered")

    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame:
        from providers.bootstrap import get_registry

        dividend_provider = get_registry().get_dividend_provider()
        if dividend_provider:
            return dividend_provider.fetch_dividend_history(ticker, start_date, end_date, **kw)
        raise ValueError("No dividend provider registered")

    def fetch_current_dividend_yield(self, ticker, **kw) -> float:
        from providers.bootstrap import get_registry

        dividend_provider = get_registry().get_dividend_provider()
        if dividend_provider:
            return dividend_provider.fetch_current_dividend_yield(ticker, **kw)
        return 0.0


def set_price_provider(provider: PriceProvider) -> None:
    global _price_provider
    _price_provider = provider


def get_price_provider() -> PriceProvider:
    global _price_provider
    if _price_provider is None:
        _price_provider = _RegistryBackedPriceProvider()
    return _price_provider


def set_fx_provider(provider: FXProvider) -> None:
    global _fx_provider
    _fx_provider = provider


def get_fx_provider() -> FXProvider:
    global _fx_provider
    if _fx_provider is None:
        from portfolio_risk_engine._fmp_provider import FMPFXProvider

        _fx_provider = FMPFXProvider()
    return _fx_provider


def set_currency_resolver(resolver: CurrencyResolver) -> None:
    global _currency_resolver
    _currency_resolver = resolver


def get_currency_resolver() -> CurrencyResolver:
    global _currency_resolver
    if _currency_resolver is None:
        from portfolio_risk_engine._fmp_provider import FMPCurrencyResolver

        _currency_resolver = FMPCurrencyResolver()
    return _currency_resolver
