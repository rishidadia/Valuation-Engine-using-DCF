"""Provider abstraction.

    DataProvider (abstract)
        ├── PublicCompanyProvider   (public market + SEC fundamentals)
        └── ExcelProvider           (uploaded workbook)

The valuation engine only ever consumes `ProviderPayload`, so a new provider
can be added without touching valuation code.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any

import httpx

from ...core.config import settings
from ...core.errors import ProviderError, ProviderUnavailableError
from ...schemas.common import SourceRecord
from ...schemas.company import CompanyInfo, PeriodData
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MarketSnapshot(BaseModel):
    """Observable market data needed for WACC/equity bridge."""

    share_price: float | None = None
    price_currency: str | None = None
    price_date: date | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None
    beta: float | None = None
    beta_r_squared: float | None = None
    beta_observations: int | None = None
    beta_source: str | None = None
    risk_free_rate: float | None = None
    risk_free_source: str | None = None
    price_history: list[dict] = Field(default_factory=list)  # [{date, close}] for charts
    warnings: list[str] = Field(default_factory=list)

    # Provenance labels for non-US markets (e.g. NSE). Optional and additive:
    # when unset the assumption layer keeps its existing Yahoo/SEC/FRED wording.
    market: str | None = None  # "US" | "IN"
    price_provider: str | None = None
    price_source_url: str | None = None
    beta_provider: str | None = None
    beta_source_url: str | None = None
    shares_provider: str | None = None
    risk_free_is_estimate: bool = False


class ProviderPayload(BaseModel):
    """Normalized output every provider must produce."""

    company: CompanyInfo
    periods: list[PeriodData] = Field(default_factory=list)
    market: MarketSnapshot = Field(default_factory=MarketSnapshot)
    sources: list[SourceRecord] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)  # critical metric keys not found
    warnings: list[str] = Field(default_factory=list)
    preview: list[dict] = Field(default_factory=list)


class DataProvider(ABC):
    """Abstract financial-data provider."""

    name: str = "base"
    kind: str = "unknown"  # "public" | "excel"

    @abstractmethod
    async def fetch(self, **kwargs: Any) -> ProviderPayload:
        """Retrieve and normalize data. Must never fabricate missing values."""


# --------------------------------------------------------------------------
# Shared HTTP helper: timeout, retries with backoff, rate-limit friendly
# --------------------------------------------------------------------------

RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, timeout: float | None = None, headers: dict | None = None):
        self._timeout = timeout or settings.http_timeout_seconds
        self._headers = headers or {}

    async def _request(self, method: str, url: str, *, retries: int = 3, **kwargs: Any) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            for attempt in range(retries):
                try:
                    resp = await client.request(method, url, headers=headers, **kwargs)
                    if resp.status_code in RETRY_STATUS and attempt < retries - 1:
                        await asyncio.sleep(0.8 * (2 ** attempt))
                        continue
                    return resp
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    last_exc = exc
                    await asyncio.sleep(0.8 * (2 ** attempt))
        raise ProviderUnavailableError(
            f"Request to {url} failed after {retries} attempts: {last_exc}",
            hint="The external data source may be unavailable or rate-limiting. Retry later.",
        )

    async def json(self, url: str, **kwargs: Any) -> Any:
        resp = await self._request("GET", url, **kwargs)
        if resp.status_code == 404:
            raise ProviderError(f"Resource not found: {url}")
        if resp.status_code == 429:
            raise ProviderError(
                f"Rate limited by {url}",
                hint="The data provider limited requests. Wait briefly and retry.",
            )
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code} from {url}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"Invalid JSON from {url}: {exc}") from exc

    async def text(self, url: str, **kwargs: Any) -> str:
        resp = await self._request("GET", url, **kwargs)
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code} from {url}")
        return resp.text


def today() -> date:
    return datetime.now(timezone.utc).date()
