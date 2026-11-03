"""FRED risk-free rate — 10-year US Treasury constant maturity (keyless CSV).

Source: Federal Reserve Bank of St. Louis (DGS10). Units: percent per annum.
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

    async def latest_10y(self) -> dict:
        text = await self.http.text(settings.fred_risk_free_url)
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if r and len(r) >= 2]
        if not rows:
            raise ProviderError("FRED returned an empty series")
        header, *body = rows
        for row in reversed(body):
            val = row[1].strip()
            if val and val != ".":
                try:
                    pct = float(val)
                except ValueError:
                    continue
                return {
                    "rate": pct / 100.0,
                    "as_of": row[0],
                    "series": "DGS10",
                    "label": "10-Year US Treasury Yield",
                }
        raise ProviderError("No usable observation in FRED DGS10 series")

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
