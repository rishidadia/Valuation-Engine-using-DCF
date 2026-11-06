"""API request/response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .company import CompanyInfo, DataReview, IngestResult
from .valuation import ValuationOptions, ValuationSummary, ValuationView

# Re-exported option literal aliases (kept for API docs compatibility)
OptionCostOfEquity = Literal["capm", "manual"]
OptionBeta = Literal["market", "comparables", "manual"]
OptionCostOfDebt = Literal["interest_bearing", "instruments", "manual"]
OptionTax = Literal["historical_effective", "statutory", "manual"]
OptionCapital = Literal["current", "target", "manual"]
OptionTerminal = Literal["perpetuity_growth", "exit_multiple"]


class RunValuationRequest(BaseModel):
    company_id: str
    overrides: dict[str, float] = Field(default_factory=dict)
    options: ValuationOptions = Field(default_factory=ValuationOptions)
    scenario: Literal["base", "bull", "bear", "custom"] = "base"


class AssumptionsRequest(BaseModel):
    """User overrides: key -> final value."""

    overrides: dict[str, float] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)  # keys to reset to model estimate
    options: ValuationOptions | None = None
    recompute: bool = True


class MetricOverride(BaseModel):
    """Data Review correction: user fixes a mapped/missing value."""

    metric: str = Field(min_length=1, max_length=64)
    value: float | None = None  # None clears the override
    period: str | None = None


class MetricsPatchRequest(BaseModel):
    overrides: list[MetricOverride] = Field(default_factory=list)


class ScenarioPatchRequest(BaseModel):
    active: Literal["base", "bull", "bear", "custom"] = "base"
    overrides: dict[str, float] = Field(default_factory=dict)
    label: str | None = None
    recompute: bool = True


class PublicCompanyBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    name: str | None = Field(default=None, max_length=255)
    exchange: str | None = Field(default=None, max_length=64)
    # "IN" = NSE India (NSE filings + bhavcopy/Kite data); default/"US" = SEC EDGAR.
    # A .NS suffix also selects India, so existing US requests are unchanged.
    market: Literal["US", "IN"] | None = None
    peer_tickers: list[str] = Field(default_factory=list)
    include_comparables: bool = True


class IngestResponse(BaseModel):
    company_id: str
    mode: Literal["public", "excel"]
    review: DataReview
    warnings: list[str] = Field(default_factory=list)
    agents: list = Field(default_factory=list)


class SummaryResponse(BaseModel):
    valuation_id: str
    summary: ValuationSummary


class FullValuationResponse(BaseModel):
    valuation: ValuationView


class HealthResponse(BaseModel):
    status: str
    app: str
    database: str
    providers: list[str]
