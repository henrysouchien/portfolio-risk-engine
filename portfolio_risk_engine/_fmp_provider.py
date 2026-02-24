"""Default lazy FMP-backed providers for standalone or monorepo usage."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from portfolio_risk_engine._ticker import select_fmp_symbol


class FMPPriceProvider:
    """Thin adapter over fmp.compat with lazy imports."""

    def fetch_monthly_close(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series:
        from fmp.compat import fetch_monthly_close as _fn  # type: ignore

        return _fn(ticker, start_date, end_date, **kw)

    def fetch_monthly_total_return_price(self, ticker, start_date=None, end_date=None, **kw) -> pd.Series:
        from fmp.compat import fetch_monthly_total_return_price as _fn  # type: ignore

        return _fn(ticker, start_date, end_date, **kw)

    def fetch_monthly_treasury_rates(self, maturity: str, start_date=None, end_date=None) -> pd.Series:
        from fmp.compat import fetch_monthly_treasury_rates as _fn  # type: ignore

        return _fn(maturity, start_date, end_date)

    def fetch_dividend_history(self, ticker, start_date=None, end_date=None, **kw) -> pd.DataFrame:
        from fmp.compat import fetch_dividend_history as _fn  # type: ignore

        return _fn(ticker, start_date, end_date, **kw)

    def fetch_current_dividend_yield(self, ticker, **kw) -> float:
        # Keep this lightweight and consistent with existing implementation:
        # compute from dividend history + latest month-end close.
        fmp_symbol = select_fmp_symbol(
            ticker,
            fmp_ticker=kw.get("fmp_ticker"),
            fmp_ticker_map=kw.get("fmp_ticker_map"),
        )

        lookback_months = int((kw.get("lookback_months") or 12))
        end_month = (pd.Timestamp.today().to_period("M") - 1).to_timestamp("M")
        start_month = end_month - pd.DateOffset(months=lookback_months - 1)

        div_df = self.fetch_dividend_history(
            fmp_symbol,
            start_month,
            end_month,
            fmp_ticker=fmp_symbol,
        )
        if isinstance(div_df, pd.Series):
            div_df = div_df.to_frame(name="adjDividend")
        if div_df is None or div_df.empty:
            return 0.0

        annual_dividends = pd.to_numeric(
            div_df.get("adjDividend", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0).sum()

        prices = self.fetch_monthly_close(
            fmp_symbol,
            None,
            end_month.date().isoformat(),
            fmp_ticker=fmp_symbol,
        )
        if prices is None or prices.dropna().empty:
            return 0.0

        current_price = float(prices.dropna().iloc[-1])
        if current_price <= 0 or annual_dividends <= 0:
            return 0.0

        return round(float((annual_dividends / current_price) * 100.0), 4)


class FMPFXProvider:
    """Optional FX adapter over fmp.fx."""

    def adjust_returns_for_fx(self, returns: pd.Series, currency: str, **kw):
        from fmp.fx import adjust_returns_for_fx as _fn  # type: ignore

        return _fn(returns, currency, **kw)

    def get_fx_rate(self, currency: str) -> float:
        from fmp.fx import get_fx_rate as _fn  # type: ignore

        return float(_fn(currency))
