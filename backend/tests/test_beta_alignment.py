"""Beta regression must join the stock and benchmark on actual trading dates.

The provider used to take the last N returns of each series independently,
which pairs returns from different days whenever either series has a missing
observation (holiday, halt, missing print) and silently distorts beta.
"""
from datetime import date, timedelta

import asyncio

import numpy as np
import pytest

from app.core.errors import ProviderError
from app.data.providers.yahoo import YahooPriceProvider
from app.valuation import regression_beta


def _dates(n: int) -> list[str]:
    start = date(2024, 1, 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _series(dates: list[str], *, beta: float = 1.5, drop: set[int] | None = None) -> list[dict]:
    """Closes whose returns are exactly beta x the benchmark's returns."""
    drop = drop or set()
    closes = [100.0]
    for i in range(1, len(dates)):
        bench_ret = 0.01 if i % 2 else -0.005
        closes.append(closes[-1] * (1.0 + beta * bench_ret))
    points = [{"date": d, "close": c, "adjclose": c} for d, c in zip(dates, closes)]
    return [p for i, p in enumerate(points) if i not in drop]


class _FakeYahoo(YahooPriceProvider):
    def __init__(self, series: dict[str, list[dict]]) -> None:
        super().__init__()
        self._series = series

    async def history(self, symbol: str, range_: str = "2y", interval: str = "1d") -> dict:  # noqa: ARG002
        return {"meta": {}, "points": self._series[symbol]}


def test_beta_uses_date_aligned_returns():
    dates = _dates(24)
    # Stock is missing one day, the benchmark a different day.
    stock = _series(dates, drop={7})
    bench = _series(dates, beta=1.0, drop={15})

    provider = _FakeYahoo({"XYZ": stock, "SPY": bench})
    out = asyncio.run(provider.compute_beta("XYZ"))

    by_date_s = {p["date"]: p["adjclose"] for p in stock}
    by_date_b = {p["date"]: p["adjclose"] for p in bench}
    common = sorted(set(by_date_s) & set(by_date_b))
    cs = np.array([by_date_s[d] for d in common])
    cb = np.array([by_date_b[d] for d in common])
    expected, _, _ = regression_beta(np.diff(cs) / cs[:-1], np.diff(cb) / cb[:-1])

    # The last-N pairing the provider used to do pairs different dates, so its
    # slope differs from the date-aligned regression on the same data.
    n = min(len(stock), len(bench)) - 1
    tail_s = np.diff([p["adjclose"] for p in stock[-(n + 1):]]) / np.array(
        [p["adjclose"] for p in stock[-(n + 1):-1]])
    tail_b = np.diff([p["adjclose"] for p in bench[-(n + 1):]]) / np.array(
        [p["adjclose"] for p in bench[-(n + 1):-1]])
    tail, _, _ = regression_beta(tail_s, tail_b)

    assert out["observations"] == len(common) - 1
    assert out["dropped_observations"] == 2
    assert out["beta"] == pytest.approx(round(float(expected), 4), abs=1e-4)
    assert abs(tail - expected) > 0.01  # the old index alignment is demonstrably wrong
    assert out["window"].startswith("2y daily, date-aligned")


def test_beta_rejects_too_little_overlap():
    dates = _dates(24)
    stock = _series(dates, drop=set(range(5, 24)))
    bench = _series(dates, beta=1.0)
    provider = _FakeYahoo({"XYZ": stock, "SPY": bench})

    with pytest.raises(ProviderError) as ei:
        asyncio.run(provider.compute_beta("XYZ"))
    assert "overlapping trading days" in ei.value.detail
