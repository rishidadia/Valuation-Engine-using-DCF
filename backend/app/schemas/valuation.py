"""Valuation pipeline schemas: analysis, forecast, WACC, FCF, DCF,
sensitivity, scenarios, comparables, report — all traceable."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .common import (
    AgentRun,
    Assumption,
    AuditResult,
    CheckStatus,
    SourceRecord,
    SourceType,
    SourcedValue,
)
from .company import CompanyInfo, PeriodData


class ValuationOptions(BaseModel):
    """Non-numeric model choices (numeric inputs live in assumptions)."""

    cost_of_equity_method: Literal["capm", "manual"] = "capm"
    beta_method: Literal["market", "comparables", "manual"] = "market"
    cost_of_debt_method: Literal["interest_bearing", "instruments", "manual"] = "interest_bearing"
    tax_rate_method: Literal["historical_effective", "statutory", "manual"] = "historical_effective"
    capital_structure_method: Literal["current", "target", "manual"] = "current"
    terminal_method: Literal["perpetuity_growth", "exit_multiple"] = "perpetuity_growth"
    beta_aggregation: Literal["median", "mean"] = "median"
    discount_convention: Literal["end", "mid"] = "end"
    forecast_years: int = Field(default=5, ge=1, le=15)
    # Optional forecast trajectories (decimals). Empty -> constant drivers.
    growth_path: list[float] | None = None
    ebit_margin_path: list[float] | None = None
    growth_fade_to_terminal: bool = False
    margin_convergence_years: int = Field(default=0, ge=0, le=15)
    peer_tickers: list[str] = Field(default_factory=list)
    run_comparables: bool = True
    run_sensitivity: bool = True


# ---------------- Historical analysis ----------------

class RatioRow(BaseModel):
    period: str
    fiscal_year: int
    values: dict[str, SourcedValue] = Field(default_factory=dict)


class HistoricalAnalysis(BaseModel):
    periods: list[str] = Field(default_factory=list)
    rows: list[RatioRow] = Field(default_factory=list)
    summary: dict[str, SourcedValue] = Field(default_factory=dict)  # CAGR, averages
    facts: list[str] = Field(default_factory=list)  # computed observations
    interpretation: list[str] = Field(default_factory=list)  # qualitative, clearly labelled
    proposed_assumptions: list[Assumption] = Field(default_factory=list)


# ---------------- Forecast ----------------

class ForecastYear(BaseModel):
    period: str
    year_index: int
    revenue_growth: SourcedValue
    revenue: SourcedValue
    ebit_margin: SourcedValue
    ebit: SourcedValue
    da: SourcedValue
    capex: SourcedValue
    change_nwc: SourcedValue
    ebitda: SourcedValue
    driver_note: str = ""


class ForecastResult(BaseModel):
    method: str = "historical_drift"
    years: list[ForecastYear] = Field(default_factory=list)
    start_period: str
    assumptions_used: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    alternative: dict | None = None  # optional statistical/ML comparison payload


# ---------------- WACC ----------------

class BetaDetail(BaseModel):
    ticker: str | None = None
    name: str | None = None
    levered_beta: float | None = None
    tax_rate: float | None = None
    debt_equity: float | None = None
    unlevered_beta: float | None = None
    selected: bool = True
    note: str | None = None


class WaccCalculation(BaseModel):
    market_value_equity: SourcedValue
    market_value_debt: SourcedValue
    equity_weight: SourcedValue
    debt_weight: SourcedValue
    risk_free_rate: SourcedValue
    beta: SourcedValue
    market_risk_premium: SourcedValue
    cost_of_equity: SourcedValue
    cost_of_debt: SourcedValue
    after_tax_cost_of_debt: SourcedValue
    tax_rate: SourcedValue
    wacc: SourcedValue
    capm_formula: str = ""
    wacc_formula: str = ""
    cost_of_equity_method: Literal["capm", "manual"] = "capm"
    beta_method: Literal["market", "comparables", "manual"] = "market"
    cost_of_debt_method: Literal["interest_bearing", "instruments", "manual"] = "interest_bearing"
    tax_rate_method: Literal["historical_effective", "statutory", "manual"] = "historical_effective"
    capital_structure_method: Literal["current", "target", "manual"] = "current"
    beta_details: list[BetaDetail] = Field(default_factory=list)
    debt_instruments: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------- FCF ----------------

class FcfYear(BaseModel):
    period: str
    year_index: int
    revenue: SourcedValue
    ebit: SourcedValue
    tax_rate: SourcedValue
    tax_expense: SourcedValue
    nopat: SourcedValue
    da: SourcedValue
    capex: SourcedValue
    change_nwc: SourcedValue
    fcf: SourcedValue
    discount_factor: float | None = None
    pv_fcf: float | None = None
    formula: str = ""


class FcfSchedule(BaseModel):
    years: list[FcfYear] = Field(default_factory=list)
    fcf_cagr: float | None = None
    margins: list[float] = Field(default_factory=list)  # FCF margin per year
    notes: list[str] = Field(default_factory=list)


# ---------------- DCF ----------------

class TerminalMethodResult(BaseModel):
    method: Literal["perpetuity_growth", "exit_multiple"]
    label: str
    terminal_value: float | None = None
    pv_terminal_value: float | None = None
    formula: str = ""
    inputs: dict[str, float] = Field(default_factory=dict)
    valid: bool = True
    issue: str | None = None
    ev: float | None = None
    equity_value: float | None = None
    implied_share_price: float | None = None


class DcfResult(BaseModel):
    discount_rate: float
    forecast_years: int
    pv_rows: list[dict] = Field(default_factory=list)  # period, fcf, df, pv
    pv_forecast_fcf: float = 0.0
    terminal_methods: list[TerminalMethodResult] = Field(default_factory=list)
    selected_method: Literal["perpetuity_growth", "exit_multiple"] = "perpetuity_growth"
    enterprise_value: float | None = None
    cash: float | None = None
    debt: float | None = None
    equity_value: float | None = None
    shares_outstanding: float | None = None
    implied_share_price: float | None = None
    current_share_price: float | None = None
    upside_downside: float | None = None
    terminal_growth: float | None = None
    exit_multiple: float | None = None
    fcf_cagr: float | None = None
    bridge: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    valid: bool = True
    issue: str | None = None


# ---------------- Sensitivity ----------------

class SensitivityTable(BaseModel):
    key: str
    title: str
    row_label: str
    col_label: str
    row_values: list[float] = Field(default_factory=list)
    col_values: list[float] = Field(default_factory=list)
    matrix: list[list[float | None]] = Field(default_factory=list)
    base_value: float | None = None
    base_row: float | None = None
    base_col: float | None = None
    unit: Literal["price", "ev", "equity"] = "price"
    note: str | None = None


class TornadoItem(BaseModel):
    input_key: str
    label: str
    low: float
    high: float
    low_result: float | None = None
    high_result: float | None = None
    base_result: float | None = None
    swing: float | None = None
    note: str | None = None


class SensitivityResult(BaseModel):
    tables: list[SensitivityTable] = Field(default_factory=list)
    tornado: list[TornadoItem] = Field(default_factory=list)
    base_implied_price: float | None = None
    notes: list[str] = Field(default_factory=list)


# ---------------- Scenarios ----------------

class ScenarioDef(BaseModel):
    name: Literal["base", "bull", "bear", "custom"] = "base"
    label: str = "Base Case"
    overrides: dict[str, float] = Field(default_factory=dict)
    description: str = ""


class ScenarioResult(BaseModel):
    name: str
    label: str
    overrides: dict[str, float] = Field(default_factory=dict)
    wacc: float | None = None
    terminal_growth: float | None = None
    enterprise_value: float | None = None
    equity_value: float | None = None
    implied_share_price: float | None = None
    upside_downside: float | None = None
    valid: bool = True
    issue: str | None = None


class ScenarioComparison(BaseModel):
    active: str = "base"
    scenarios: list[ScenarioResult] = Field(default_factory=list)


# ---------------- Comparables ----------------

class PeerMetrics(BaseModel):
    ticker: str
    name: str | None = None
    currency: str | None = None
    ev: float | None = None
    revenue: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    net_income: float | None = None
    market_cap: float | None = None
    # Gross debt and cash are kept separately (EV - market cap is NET debt and
    # must never stand in for the Hamada D/E without being flagged).
    total_debt: float | None = None
    cash: float | None = None
    tax_rate: float | None = None  # effective rate: income tax expense / EBT
    debt_equity: float | None = None  # gross debt / market cap
    ev_revenue: float | None = None
    ev_ebitda: float | None = None
    ev_ebit: float | None = None
    pe: float | None = None
    levered_beta: float | None = None
    source: str = "SEC EDGAR / Yahoo Finance"
    source_url: str | None = None
    retrieved_at: date | None = None
    note: str | None = None


class ComparablesResult(BaseModel):
    status: Literal["ok", "insufficient_data"] = "insufficient_data"
    peers: list[PeerMetrics] = Field(default_factory=list)
    multiple_stats: dict[str, dict] = Field(default_factory=dict)  # name -> {median, mean, count}
    implied_values: list[dict] = Field(default_factory=list)  # per-multiple implied EV/equity/price
    subject_metrics: dict[str, float | None] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    dcf_vs_comps: dict | None = None


# ---------------- Report ----------------

ReportSectionKind = Literal[
    "FACT", "CALCULATION", "ASSUMPTION", "USER OVERRIDE", "MODEL ESTIMATE", "NARRATIVE", "WARNING"
]


class ReportSection(BaseModel):
    heading: str
    kind: ReportSectionKind = "NARRATIVE"
    body: str = ""
    table: dict | None = None  # {columns: [...], rows: [[...]]}


class ReportDoc(BaseModel):
    title: str
    subtitle: str = ""
    generated_at: datetime | None = None
    disclaimer: str = (
        "This valuation is model-based and highly sensitive to assumptions. "
        "It is not investment advice."
    )
    sections: list[ReportSection] = Field(default_factory=list)
    audit_status: CheckStatus = CheckStatus.PASS
    markdown: str = ""
    llm_used: bool = False


# ---------------- Full valuation view ----------------

class ValuationSummary(BaseModel):
    id: str | None = None
    status: Literal["complete", "blocked", "draft"] = "draft"
    company: CompanyInfo
    created_at: datetime | None = None
    current_share_price: float | None = None
    implied_share_price: float | None = None
    upside_downside: float | None = None
    enterprise_value: float | None = None
    equity_value: float | None = None
    wacc: float | None = None
    terminal_growth: float | None = None
    fcf_cagr: float | None = None
    audit_status: CheckStatus = CheckStatus.PASS
    blocked_reasons: list[str] = Field(default_factory=list)


class ValuationView(BaseModel):
    """Everything the frontend needs; also the persisted JSON artifact."""

    summary: ValuationSummary
    company: CompanyInfo
    options: ValuationOptions | None = None
    historical_periods: list[PeriodData] = Field(default_factory=list)
    forecast: ForecastResult | None = None
    historical: HistoricalAnalysis | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    wacc: WaccCalculation | None = None
    fcf: FcfSchedule | None = None
    dcf: DcfResult | None = None
    sensitivity: SensitivityResult | None = None
    scenarios: ScenarioComparison | None = None
    comparables: ComparablesResult | None = None
    audit: AuditResult | None = None
    report: ReportDoc | None = None
    agents: list[AgentRun] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
