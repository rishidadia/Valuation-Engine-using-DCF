"""FRED risk-free rates — keyless CSV series.

US:  ``DGS10``            10-year US Treasury constant maturity (daily).
IN:  ``INDIRLTLT01STM``   India 10-year government bond yield (monthly, OECD).
Units: percent per annum.
"""
from __future__ import annotations

import csv
import io

from ...core.config import settings
from ...core.errors import ProviderError
from ...schemas.common import SourceRecord, SourceType
from .base import HttpClient, today


class FredRiskFreeProvider:
    name = "fred"

    def __init__(self) -> None:
        self.http = HttpClient(headers={"User-Agent": "dcf-labs/1.0"})

    async def _latest(self, url: str, series: str) -> dict:
        text = await self.http.text(url)
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if r and len(r) >= 2]
        if not rows:
            raise ProviderError(f"FRED returned an empty series ({series})")
        _header, *body = rows
        for row in reversed(body):
            val = row[1].strip()
            if val and val != ".":
                try:
                    pct = float(val)
                except ValueError:
                    continue
                return {"rate": pct / 100.0, "as_of": row[0]}
        raise ProviderError(f"No usable observation in FRED {series} series")

    async def latest_10y(self) -> dict:
        obs = await self._latest(settings.fred_risk_free_url, "DGS10")
        return {**obs, "series": "DGS10", "label": "10-Year US Treasury Yield"}

    async def latest_india_10y(self) -> dict:
        obs = await self._latest(settings.india_risk_free_url, "INDIRLTLT01STM")
        return {**obs, "series": "INDIRLTLT01STM",
                "label": "India 10-Year Government Bond Yield"}

    async def source_record(self) -> SourceRecord:
        obs = await self.latest_10y()
        return SourceRecord(
            id="fred-dgs10",
            name=f"FRED DGS10 — 10Y Treasury ({obs['as_of']})",
            source_type=SourceType.PUBLIC_API,
            url="https://fred.stlouisfed.org/series/DGS10",
            retrieved_at=today(),
            description="Risk-free rate proxy: 10-year US Treasury constant-maturity yield.",
            metrics=["risk_free_rate"],
        )

    async def india_source_record(self) -> SourceRecord:
        obs = await self.latest_india_10y()
        return SourceRecord(
            id="fred-india-10y",
            name=f"FRED INDIRLTLT01STM — India 10Y G-Sec ({obs['as_of']})",
            source_type=SourceType.PUBLIC_API,
            url="https://fred.stlouisfed.org/series/INDIRLTLT01STM",
            retrieved_at=today(),
            description=("Risk-free rate proxy for India: 10-year government bond yield "
                         "(monthly, OECD series republished by FRED)."),
            metrics=["risk_free_rate"],
        )
