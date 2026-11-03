"""Shared schema primitives: source traceability, assumptions, agent runs.

Every important number in DCF labs carries provenance:
source type, source label, URL, retrieval date, confidence, override flag.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    PUBLIC_API = "PUBLIC_API"
    UPLOADED_EXCEL = "UPLOADED_EXCEL"
    USER_INPUT = "USER_INPUT"
    MODEL_CALCULATION = "MODEL_CALCULATION"
    MODEL_ASSUMPTION = "MODEL_ASSUMPTION"
    USER_OVERRIDE = "USER_OVERRIDE"


class Unit(str, Enum):
    CURRENCY = "currency"
    PERCENT = "percent"
    RATIO = "ratio"
    MULTIPLE = "multiple"
    COUNT = "count"
    TEXT = "text"


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class ValueStatus(str, Enum):
    RETRIEVED = "Retrieved"
    ESTIMATED = "Estimated"
    CALCULATED = "Calculated"
    OVERRIDE = "Override"
    MISSING = "Missing"
    USER_DATA = "User Data"


class SourcedValue(BaseModel):
    """A single number with full provenance."""

    value: float | None = None
    unit: Unit = Unit.CURRENCY
    currency: str | None = None
    period: str | None = None
    source_type: SourceType = SourceType.MODEL_CALCULATION
    source: str = "unknown"
    source_url: str | None = None
    retrieved_at: date | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_user_override: bool = False
    status: ValueStatus = ValueStatus.CALCULATED
    note: str | None = None
    original_value: float | None = None  # as originally reported (pre unit conversion)
    original_unit: str | None = None
    cell_ref: str | None = None  # for Excel provenance e.g. "Income Statement!C7"

    @property
    def available(self) -> bool:
        return self.value is not None


class Assumption(BaseModel):
    """One model input with historical / model / user / final values."""

    model_config = {"protected_namespaces": ()}

    key: str
    label: str
    group: str = "general"
    value: float | None = None  # final value actually used
    unit: Unit = Unit.RATIO
    currency: str | None = None
    historical_value: float | None = None
    model_estimate: float | None = None
    user_value: float | None = None
    source_type: SourceType = SourceType.MODEL_ASSUMPTION
    source: str = "Model"
    source_url: str | None = None
    retrieved_at: date | None = None
    status: ValueStatus = ValueStatus.ESTIMATED
    editable: bool = True
    min_value: float | None = None
    max_value: float | None = None
    note: str | None = None

    @property
    def is_override(self) -> bool:
        return self.source_type == SourceType.USER_OVERRIDE


class SourceRecord(BaseModel):
    id: str
    name: str
    source_type: SourceType
    url: str | None = None
    retrieved_at: date | None = None
    description: str | None = None
    metrics: list[str] = Field(default_factory=list)


AgentStatus = Literal["pending", "running", "success", "warning", "failed", "skipped"]


class AgentRun(BaseModel):
    """What the UI shows: status, action, result, warnings, sources. No chain-of-thought."""

    agent: str
    key: str
    status: AgentStatus = "pending"
    action: str = ""
    result: str = ""
    warnings: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    llm_used: bool = False


class Check(BaseModel):
    name: str
    status: CheckStatus
    detail: str
    severity: Literal["info", "warning", "critical"] = "info"
    related: str | None = None


class AuditResult(BaseModel):
    status: CheckStatus = CheckStatus.PASS
    checks: list[Check] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    can_finalize: bool = True


class ErrorDetail(BaseModel):
    code: str
    detail: str
    hint: str | None = None


# --- Canonical metric keys used across providers -------------------------

INCOME_METRICS = [
    "revenue", "cogs", "gross_profit", "operating_expenses", "ebit",
    "interest_expense", "ebt", "income_tax_expense", "net_income", "da",
]
CASHFLOW_METRICS = [
    "operating_cash_flow", "da_cf", "capex", "change_nwc",
]
BALANCE_METRICS = [
    "cash", "short_term_debt", "long_term_debt", "total_debt",
    "current_assets", "current_liabilities", "accounts_receivable",
    "inventory", "accounts_payable", "total_assets", "total_liabilities",
    "shareholders_equity", "shares_outstanding",
]

HISTORICAL_METRICS = INCOME_METRICS + CASHFLOW_METRICS + BALANCE_METRICS + ["ebitda"]

METRIC_LABELS: dict[str, str] = {
    "revenue": "Revenue",
    "cogs": "Cost of Goods Sold",
    "gross_profit": "Gross Profit",
    "operating_expenses": "Operating Expenses",
    "ebit": "EBIT / Operating Profit",
    "interest_expense": "Interest Expense",
    "ebt": "Earnings Before Tax",
    "income_tax_expense": "Income Tax Expense",
    "net_income": "Net Income",
    "da": "Depreciation & Amortization",
    "ebitda": "EBITDA",
    "operating_cash_flow": "Operating Cash Flow",
    "da_cf": "D&A (Cash Flow)",
    "capex": "Capital Expenditure",
    "change_nwc": "Change in Net Working Capital",
    "cash": "Cash & Equivalents",
    "short_term_debt": "Short-Term Debt",
    "long_term_debt": "Long-Term Debt",
    "total_debt": "Total Debt",
    "current_assets": "Current Assets",
    "current_liabilities": "Current Liabilities",
    "accounts_receivable": "Accounts Receivable",
    "inventory": "Inventory",
    "accounts_payable": "Accounts Payable",
    "total_assets": "Total Assets",
    "total_liabilities": "Total Liabilities",
    "shareholders_equity": "Shareholders' Equity",
    "shares_outstanding": "Shares Outstanding",
}
