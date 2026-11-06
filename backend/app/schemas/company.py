"""Company + ingested financial statement schemas (both entry modes)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .common import AgentRun, ErrorDetail, SourceRecord, SourceType, SourcedValue, ValueStatus


class CompanyInfo(BaseModel):
    id: str | None = None
    name: str
    ticker: str | None = None
    exchange: str | None = None
    cik: str | None = None
    isin: str | None = None
    currency: str = "USD"
    industry: str | None = None
    sector: str | None = None
    sic_code: str | None = None
    is_public: bool = True
    description: str | None = None
    source_type: SourceType = SourceType.PUBLIC_API
    source: str = "unknown"
    source_url: str | None = None
    retrieved_at: date | None = None
    provider: str | None = None
    notes: list[str] = Field(default_factory=list)


class PeriodData(BaseModel):
    """One reporting period of normalized financials."""

    period: str  # e.g. FY2023
    fiscal_year: int
    end_date: date | None = None
    period_type: Literal["annual", "quarterly", "ttm"] = "annual"
    is_forecast: bool = False
    currency: str = "USD"
    unit_scale: float = 1.0  # multiplier applied to reach absolute currency units
    metrics: dict[str, SourcedValue] = Field(default_factory=dict)

    def get(self, key: str) -> SourcedValue | None:
        return self.metrics.get(key)

    def value(self, key: str) -> float | None:
        mv = self.metrics.get(key)
        return mv.value if mv else None


class MappingNote(BaseModel):
    """Excel mapping decision the user can review/correct on the Data Review page."""

    field: str
    field_label: str
    mapped_from: str | None = None  # e.g. "'Income Statement'!B7 (label: 'Total Revenue')"
    confidence: float = 0.0
    period: str | None = None
    ambiguous: bool = False
    candidates: list[str] = Field(default_factory=list)


class IngestResult(BaseModel):
    company: CompanyInfo
    periods: list[PeriodData] = Field(default_factory=list)
    mapping_notes: list[MappingNote] = Field(default_factory=list)
    missing_critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    agents: list[AgentRun] = Field(default_factory=list)
    raw_preview: list[dict] = Field(default_factory=list)  # workbook sheet/row preview
    errors: list[ErrorDetail] = Field(default_factory=list)


class DataReviewRow(BaseModel):
    """Field | Value | Period | Source | Status — the Data Review table."""

    key: str
    field: str
    value: float | None = None
    display: str | None = None
    unit: str = "currency"
    currency: str | None = None
    period: str | None = None
    source: str
    source_type: SourceType
    status: ValueStatus
    critical: bool = False
    note: str | None = None
    cell_ref: str | None = None


class DataReview(BaseModel):
    company: CompanyInfo
    rows: list[DataReviewRow] = Field(default_factory=list)
    missing_critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)


class PublicCompanyRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    name: str | None = None
    exchange: str | None = None
    market: Literal["US", "IN"] | None = None  # None = infer (US unless .NS)
    include_comparables: bool = True
    peer_tickers: list[str] = Field(default_factory=list)
