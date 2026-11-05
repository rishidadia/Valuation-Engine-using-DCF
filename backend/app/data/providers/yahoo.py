"""Yahoo Finance chart provider — keyless share prices and beta inputs.

Beta is NOT taken from an opaque vendor field: it is computed by our own OLS
regression of the stock's daily returns against SPY, fully transparent.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np

from ...core.config import settings
from ...core.errors import ProviderError, TickerNotFoundError
from .base import HttpClient


class YahooPriceProvider:
    name = "yahoo_finance"

    def __init__(self) -> None:
        self.http = HttpClient(headers={"User-Agent": _UA})

    async def history(self, symbol: str, range_: str = "2y", interval: str = "1d") -> dict:
        url = settings.yahoo_chart_url.format(symbol=symbol)
        data = await self.http.json(url, params={"range": range_, "interval": interval})
        chart = data.get("chart", {})
        if chart.get("error"):
            code = chart["error"].get("code")
            desc = chart["error"].get("description", "unknown error")
            if code in ("Not Found", "No data found"):
                raise TickerNotFoundError(f"Yahoo Finance has no data for '{symbol}': {desc}")
            raise ProviderError(f"Yahoo Finance error for '{symbol}': {desc}")
        results = chart.get("result") or []
        if not results:
            raise TickerNotFoundError(f"No market data for '{symbol}'.")
        res = results[0]
        meta = res.get("meta", {})
        ts = res.get("timestamp") or []
        quote = ((res.get("indicators", {}).get("quote") or [{}])[0]).get("close") or []
        adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0]).get("adjclose") or quote
        points = []
        for t, c, a in zip(ts, quote, adj if adj else quote):
            if c is None:
                continue
            points.append({
                "date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
                "close": float(c),
                "adjclose": float(a if a is not None else c),
            })
        return {"meta": meta, "points": points}

    async def daily_returns(self, symbol: str, range_: str = "2y") -> tuple[list[str], np.ndarray]:
        hist = await self.history(symbol, range_)
        pts = hist["points"]
        if len(pts) < 2:
            raise ProviderError(f"Insufficient price history for '{symbol}'")
        closes = np.array([p["adjclose"] for p in pts], dtype=float)
        rets = np.diff(closes) / closes[:-1]
        dates = [p["date"] for p in pts[1:]]
        return dates, rets

    async def latest_price(self, symbol: str) -> dict:
        hist = await self.history(symbol, range_="5d", interval="1d")
        meta = hist["meta"]
        pts = hist["points"]
        if not pts:
            raise ProviderError(f"No recent price for '{symbol}'")
        last = pts[-1]
        return {
            "price": float(meta.get("regularMarketPrice") or last["close"]),
            "currency": meta.get("currency"),
            "date": date.fromisoformat(last["date"]),
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
            "instrument": meta.get("instrumentType"),
        }

    async def compute_beta(self, symbol: str, benchmark: str = "SPY") -> dict:
        """OLS beta vs benchmark on **date-aligned** daily returns (2y).

        Prices are joined on the actual trading date and returns are computed
        from the aligned price series. Holidays, halts, or missing prints differ
        between the stock and the benchmark, so taking the last N returns of each
        series separately would silently pair returns from different days (and
        different horizons) and corrupt the regression. Dates present in only
        one series are dropped.
        """
        from ...valuation.beta import regression_beta

        stock_hist = await self.history(symbol)
        bench_hist = await self.history(benchmark)
        stock_by_date = {p["date"]: float(p["adjclose"]) for p in stock_hist["points"]}
        bench_by_date = {p["date"]: float(p["adjclose"]) for p in bench_hist["points"]}
        common = sorted(set(stock_by_date) & set(bench_by_date))
        if len(common) < 13:
            raise ProviderError(
                f"Only {max(len(common) - 1, 0)} overlapping trading days between "
                f"'{symbol}' and '{benchmark}' — at least 12 are needed to estimate beta.",
                hint="Request a longer price history or provide beta manually.",
            )
        closes_s = np.array([stock_by_date[d] for d in common], dtype=float)
        closes_b = np.array([bench_by_date[d] for d in common], dtype=float)
        s = np.diff(closes_s) / closes_s[:-1]
        b = np.diff(closes_b) / closes_b[:-1]
        beta, alpha, r2 = regression_beta(s, b)
        dropped = (len(stock_by_date) - len(common)) + (len(bench_by_date) - len(common))
        return {
            "beta": round(float(beta), 4),
            "alpha_daily": float(alpha),
            "r_squared": round(float(r2), 4),
            "observations": int(len(common) - 1),
            "benchmark": benchmark,
            "window": f"2y daily, date-aligned ({common[0]} to {common[-1]})",
            "dropped_observations": int(dropped),
        }


async def daily_returns(symbol: str, range_: str = "2y"):
    """Module-level convenience for tests."""
    return await YahooPriceProvider().daily_returns(symbol, range_)


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
