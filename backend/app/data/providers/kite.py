"""Zerodha Kite Connect — optional market data for NSE-listed companies.

Kite is used for prices only (last traded price and daily closes for the beta
regression). Fundamentals always come from NSE filings — Kite has no financial
statements, and this provider never guesses them.

Credentials are never hardcoded: set ``KITE_API_KEY`` and ``KITE_ACCESS_TOKEN``
(the daily token produced by Kite's login flow). Without both, the NSE bhavcopy
path is used instead.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from ...core.config import settings
from ...core.errors import ProviderError
from .base import today
from .nse import NseIndiaProvider

logger = logging.getLogger(__name__)


class KiteMarketProvider:
    name = "zerodha_kite"

    def __init__(self) -> None:
        self.api_key = (settings.kite_api_key or "").strip()
        self.access_token = (settings.kite_access_token or "").strip()
        self._client: Any = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.access_token)

    @property
    def available(self) -> bool:
        """Configured *and* the optional ``kiteconnect`` package is installed."""
        if not self.configured:
            return False
        try:
            import kiteconnect  # noqa: F401
        except ImportError:
            logger.info("KITE_API_KEY is set but kiteconnect is not installed.")
            return False
        return True

    def _kite(self) -> Any:
        if self._client is None:
            try:
                from kiteconnect import KiteConnect
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise ProviderError(
                    "Zerodha Kite is configured but the kiteconnect package is not installed.",
                    hint="Run `pip install kiteconnect` or unset KITE_API_KEY/KITE_ACCESS_TOKEN.",
                ) from exc
            self._client = KiteConnect(api_key=self.api_key)
            self._client.set_access_token(self.access_token)
        return self._client

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """kiteconnect is synchronous — run it off the event loop."""
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - Kite raises many exception types
            raise ProviderError(
                f"Zerodha Kite request failed: {exc}",
                hint="Kite access tokens expire daily; regenerate KITE_ACCESS_TOKEN.",
            ) from exc

    async def _quote(self, symbol: str) -> dict:
        kite = self._kite()
        key = f"NSE:{symbol.strip().upper()}"
        data = await self._call(kite.quote, [key])
        quote = (data or {}).get(key)
        if not quote:
            raise ProviderError(f"Zerodha Kite returned no quote for '{key}'.")
        return quote

    async def latest_price(self, symbol: str) -> dict:
        quote = await self._quote(symbol)
        price = quote.get("last_price")
        if price is None:
            raise ProviderError(f"Zerodha Kite returned no last price for '{symbol}'.")
        stamp = quote.get("last_trade_time")
        return {
            "price": float(price),
            "currency": "INR",
            "date": stamp.date() if isinstance(stamp, datetime) else today(),
            "exchange": "NSE",
            "instrument": "EQ",
        }

    async def history(self, symbol: str, days: int = 730) -> dict[date, float]:
        """Daily closes keyed by trading date."""
        quote = await self._quote(symbol)
        token = quote.get("instrument_token")
        if not token:
            raise ProviderError(f"Zerodha Kite returned no instrument token for '{symbol}'.")
        kite = self._kite()
        end = today()
        start = end - timedelta(days=days)
        rows = await self._call(kite.historical_data, token, start, end, "day")
        out: dict[date, float] = {}
        for row in rows or []:
            stamp = row.get("date")
            close = row.get("close")
            if close is None:
                continue
            if isinstance(stamp, datetime):
                day = stamp.astimezone(timezone.utc).date() if stamp.tzinfo else stamp.date()
            elif isinstance(stamp, date):
                day = stamp
            else:
                continue
            out[day] = float(close)
        return out

    async def compute_beta(self, symbol: str, days: int = 730) -> dict:
        """OLS beta of Kite daily closes vs the NSE NIFTY 50 index."""
        from ...valuation.beta import regression_beta

        stock = await self.history(symbol, days)
        end = today()
        index = await NseIndiaProvider().index_closes(end - timedelta(days=days), end)
        common = sorted(set(stock) & set(index))
        if len(common) < 13:
            raise ProviderError(
                f"Only {max(len(common) - 1, 0)} overlapping trading days between "
                f"'{symbol}' and {settings.nse_benchmark_index}.",
                hint="Provide beta manually on the Assumptions page.",
            )
        closes_s = [stock[d] for d in common]
        closes_b = [index[d] for d in common]
        s = [(closes_s[i] / closes_s[i - 1]) - 1 for i in range(1, len(closes_s))]
        b = [(closes_b[i] / closes_b[i - 1]) - 1 for i in range(1, len(closes_b))]
        beta, alpha, r2 = regression_beta(s, b)
        return {
            "beta": round(float(beta), 4),
            "alpha_daily": float(alpha),
            "r_squared": round(float(r2), 4),
            "observations": len(common) - 1,
            "benchmark": settings.nse_benchmark_index,
            "window": (f"{days} days of daily closes via Zerodha Kite, date-aligned "
                       f"({common[0]} to {common[-1]})"),
        }


def kite_available() -> bool:
    return KiteMarketProvider().available
