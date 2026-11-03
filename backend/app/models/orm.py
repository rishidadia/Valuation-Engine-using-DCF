"""SQLAlchemy models — 17 tables (spec section 13).

Every financial value carries metadata:
value, currency, unit, period, source, source_url, source_type, confidence,
is_user_override.

JSON columns hold the rich nested artifacts (forecast, sensitivity tables…);
normalized tables keep values queryable.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TraceableMixin:
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_user_override: Mapped[bool] = mapped_column(Boolean, default=False)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(255))
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    exchange: Mapped[str | None] = mapped_column(String(64))
    cik: Mapped[str | None] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    industry: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(255))
    sic_code: Mapped[str | None] = mapped_column(String(16))
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    valuations: Mapped[list["Valuation"]] = relationship(back_populates="company")


class FinancialPeriod(Base):
    __tablename__ = "financial_periods"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    period: Mapped[str] = mapped_column(String(16))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_type: Mapped[str] = mapped_column(String(16), default="annual")
    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    period_id: Mapped[str] = mapped_column(ForeignKey("financial_periods.id"), index=True)
    statement_type: Mapped[str] = mapped_column(String(32))  # income|balance|cashflow
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(32))


class FinancialMetric(Base, TraceableMixin):
    __tablename__ = "financial_metrics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    period_id: Mapped[str] = mapped_column(ForeignKey("financial_periods.id"), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cell_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[date | None] = mapped_column(Date, nullable=True)


class DebtInstrument(Base, TraceableMixin):
    __tablename__ = "debt_instruments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    maturity: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MarketDatum(Base, TraceableMixin):
    __tablename__ = "market_data"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ValuationAssumption(Base, TraceableMixin):
    __tablename__ = "valuation_assumptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(128))
    group_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    historical_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ForecastPeriod(Base, TraceableMixin):
    __tablename__ = "forecast_periods"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    period: Mapped[str] = mapped_column(String(16))
    year_index: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    driver_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class WaccCalculationRow(Base):
    __tablename__ = "wacc_calculations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    wacc: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_of_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_of_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_free_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_risk_premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class FcfCalculationRow(Base):
    __tablename__ = "fcf_calculations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    period: Mapped[str] = mapped_column(String(16))
    year_index: Mapped[int] = mapped_column(Integer)
    ebit: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_expense: Mapped[float | None] = mapped_column(Float, nullable=True)
    nopat: Mapped[float | None] = mapped_column(Float, nullable=True)
    da: Mapped[float | None] = mapped_column(Float, nullable=True)
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_nwc: Mapped[float | None] = mapped_column(Float, nullable=True)
    fcf: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    pv_fcf: Mapped[float | None] = mapped_column(Float, nullable=True)
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)


class DcfValuationRow(Base):
    __tablename__ = "dcf_valuations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    method: Mapped[str] = mapped_column(String(32))
    terminal_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    pv_terminal_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    enterprise_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_share_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class SensitivityResultRow(Base):
    __tablename__ = "sensitivity_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    analysis_type: Mapped[str] = mapped_column(String(48))  # wacc_vs_growth | wacc_vs_exit | tornado
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ScenarioModel(Base):
    __tablename__ = "scenario_models"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class ComparableCompany(Base, TraceableMixin):
    __tablename__ = "comparable_companies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceRow(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str | None] = mapped_column(ForeignKey("valuations.id"), index=True, nullable=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True, nullable=True)
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[list] = mapped_column(JSON, default=list)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    agent: Mapped[str] = mapped_column(String(64))
    agent_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditResultRow(Base):
    __tablename__ = "audit_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    valuation_id: Mapped[str] = mapped_column(ForeignKey("valuations.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    can_finalize: Mapped[bool] = mapped_column(Boolean, default=True)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    blocking_issues: Mapped[list] = mapped_column(JSON, default=list)


class Valuation(Base):
    __tablename__ = "valuations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|complete|blocked
    mode: Mapped[str] = mapped_column(String(16), default="public")  # public|excel
    active_scenario: Mapped[str] = mapped_column(String(32), default="base")
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # full ValuationView JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    company: Mapped[Company] = relationship(back_populates="valuations")
