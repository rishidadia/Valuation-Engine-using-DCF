"""Repository: persists companies, ingested statements, and valuation artifacts.

Writes the normalized rows required by the schema *and* the full JSON payload
so GET endpoints can slice sections without recomputation.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.orm import (
    AgentRunRow, AuditResultRow, ComparableCompany, Company, DcfValuationRow,
    DebtInstrument, FcfCalculationRow, FinancialMetric, FinancialPeriod,
    ForecastPeriod, MarketDatum, ScenarioModel, SensitivityResultRow,
    SourceRow, Valuation, ValuationAssumption, WaccCalculationRow,
)
from ..schemas.common import AgentRun, AuditResult, Assumption, SourceRecord
from ..schemas.company import CompanyInfo, PeriodData
from ..schemas.valuation import ValuationView


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Repository:
    def __init__(self, session: Session):
        self.session = session

    # -- companies ----------------------------------------------------------
    def save_company(self, info: CompanyInfo) -> Company:
        kwargs = dict(
            name=info.name, ticker=info.ticker, exchange=info.exchange, cik=info.cik,
            currency=info.currency, industry=info.industry, sector=info.sector,
            sic_code=info.sic_code, is_public=info.is_public, provider=info.provider,
            meta={"source": info.source, "source_url": info.source_url,
                  "retrieved_at": info.retrieved_at.isoformat() if info.retrieved_at else None,
                  "notes": info.notes},
        )
        row = Company(id=info.id, **kwargs) if info.id else Company(**kwargs)
        self.session.add(row)
        self.session.flush()
        info.id = row.id
        return row

    def get_company(self, company_id: str) -> Company | None:
        return self.session.get(Company, company_id)

    def save_periods(self, company_id: str, periods: list[PeriodData]) -> None:
        for p in periods:
            fp = FinancialPeriod(
                company_id=company_id, period=p.period, fiscal_year=p.fiscal_year,
                end_date=p.end_date, period_type=p.period_type, is_forecast=p.is_forecast,
                currency=p.currency,
            )
            self.session.add(fp)
            self.session.flush()
            for stype, keys in (
                ("income", ["revenue", "cogs", "gross_profit", "operating_expenses", "ebit",
                            "interest_expense", "ebt", "income_tax_expense", "net_income", "da", "ebitda"]),
                ("cashflow", ["operating_cash_flow", "da_cf", "capex", "change_nwc"]),
                ("balance", ["cash", "short_term_debt", "long_term_debt", "total_debt",
                             "current_assets", "current_liabilities", "accounts_receivable",
                             "inventory", "accounts_payable", "total_assets", "total_liabilities",
                             "shareholders_equity", "shares_outstanding"]),
            ):
                subset = {k: p.metrics[k] for k in keys if k in p.metrics}
                if subset:
                    self.session.add(_statement_row(fp.id, stype, subset))
            for key, sv in p.metrics.items():
                self.session.add(FinancialMetric(
                    period_id=fp.id, metric=key, value=sv.value, currency=sv.currency,
                    unit=sv.unit.value, period=sv.period, source=sv.source,
                    source_url=sv.source_url, source_type=sv.source_type.value,
                    confidence=sv.confidence, is_user_override=sv.is_user_override,
                    original_value=sv.original_value, original_unit=sv.original_unit,
                    status=sv.status.value, cell_ref=sv.cell_ref, note=sv.note,
                    retrieved_at=sv.retrieved_at,
                ))
        self.session.flush()

    def save_market(self, company_id: str, market_payload: dict) -> None:
        for metric, value, note in (
            ("share_price", market_payload.get("share_price"), market_payload.get("price_date")),
            ("market_cap", market_payload.get("market_cap"), None),
            ("beta", market_payload.get("beta"), market_payload.get("beta_source")),
            ("risk_free_rate", market_payload.get("risk_free_rate"), market_payload.get("risk_free_source")),
            ("shares_outstanding", market_payload.get("shares_outstanding"), None),
        ):
            if value is None:
                continue
            self.session.add(MarketDatum(
                company_id=company_id, metric=metric, value=float(value),
                source_type="PUBLIC_API", source=note or "provider", note=str(note) if note else None,
            ))
        self.session.flush()

    def save_debt_instruments(self, company_id: str, instruments: list[dict]) -> None:
        for d in instruments:
            self.session.add(DebtInstrument(
                company_id=company_id, name=d.get("name", "Debt"),
                amount=d.get("amount"), rate=d.get("rate"),
                source_type="UPLOADED_EXCEL", source="Uploaded Excel — Debt Schedule",
            ))
        self.session.flush()

    # -- valuations ---------------------------------------------------------
    def create_valuation(self, company_id: str, mode: str, overrides: dict | None = None) -> Valuation:
        v = Valuation(company_id=company_id, mode=mode, overrides=overrides or {})
        self.session.add(v)
        self.session.flush()
        return v

    def get_valuation(self, valuation_id: str) -> Valuation | None:
        return self.session.get(Valuation, valuation_id)

    def update_valuation_payload(self, valuation_id: str, view: ValuationView,
                                 status: str | None = None,
                                 active_scenario: str | None = None,
                                 overrides: dict | None = None) -> None:
        v = self.get_valuation(valuation_id)
        if v is None:
            return
        v.payload = view.model_dump(mode="json")
        v.updated_at = _now()
        if status:
            v.status = status
        if active_scenario:
            v.active_scenario = active_scenario
        if overrides is not None:
            v.overrides = overrides

    def replace_valuation_artifacts(self, valuation_id: str, view: ValuationView) -> None:
        """Normalized tables derived from the current ValuationView."""
        _delete_where(ValuationAssumption, ValuationAssumption.valuation_id, valuation_id, self.session)
        _delete_where(ForecastPeriod, ForecastPeriod.valuation_id, valuation_id, self.session)
        _delete_where(WaccCalculationRow, WaccCalculationRow.valuation_id, valuation_id, self.session)
        _delete_where(FcfCalculationRow, FcfCalculationRow.valuation_id, valuation_id, self.session)
        _delete_where(DcfValuationRow, DcfValuationRow.valuation_id, valuation_id, self.session)
        _delete_where(SensitivityResultRow, SensitivityResultRow.valuation_id, valuation_id, self.session)
        _delete_where(ComparableCompany, ComparableCompany.valuation_id, valuation_id, self.session)
        _delete_where(AgentRunRow, AgentRunRow.valuation_id, valuation_id, self.session)
        _delete_where(AuditResultRow, AuditResultRow.valuation_id, valuation_id, self.session)
        _delete_where(SourceRow, SourceRow.valuation_id, valuation_id, self.session)

        for a in view.assumptions:
            self.session.add(_assumption_row(valuation_id, a))
        if view.forecast:
            for y in view.forecast.years:
                self.session.add(ForecastPeriod(
                    valuation_id=valuation_id, period=y.period, year_index=y.year_index,
                    payload=y.model_dump(mode="json"), driver_note=y.driver_note,
                ))
        if view.wacc:
            w = view.wacc
            self.session.add(WaccCalculationRow(
                valuation_id=valuation_id,
                wacc=_v(w.wacc), cost_of_equity=_v(w.cost_of_equity),
                cost_of_debt=_v(w.cost_of_debt), equity_weight=_v(w.equity_weight),
                debt_weight=_v(w.debt_weight), beta=_v(w.beta),
                risk_free_rate=_v(w.risk_free_rate), market_risk_premium=_v(w.market_risk_premium),
                tax_rate=_v(w.tax_rate), payload=w.model_dump(mode="json"),
            ))
        if view.fcf:
            for y in view.fcf.years:
                self.session.add(FcfCalculationRow(
                    valuation_id=valuation_id, period=y.period, year_index=y.year_index,
                    ebit=_v(y.ebit), tax_expense=_v(y.tax_expense), nopat=_v(y.nopat),
                    da=_v(y.da), capex=_v(y.capex), change_nwc=_v(y.change_nwc),
                    fcf=_v(y.fcf), discount_factor=y.discount_factor, pv_fcf=y.pv_fcf,
                    formula=y.formula,
                ))
        if view.dcf:
            for tm in view.dcf.terminal_methods:
                self.session.add(DcfValuationRow(
                    valuation_id=valuation_id, method=tm.method,
                    terminal_value=tm.terminal_value, pv_terminal_value=tm.pv_terminal_value,
                    enterprise_value=tm.ev, equity_value=tm.equity_value,
                    implied_share_price=tm.implied_share_price,
                    payload=tm.model_dump(mode="json"),
                ))
        if view.sensitivity:
            for t in view.sensitivity.tables:
                self.session.add(SensitivityResultRow(
                    valuation_id=valuation_id, analysis_type=t.key,
                    payload=t.model_dump(mode="json"),
                ))
            self.session.add(SensitivityResultRow(
                valuation_id=valuation_id, analysis_type="tornado",
                payload={"items": [i.model_dump(mode="json") for i in view.sensitivity.tornado]},
            ))
        if view.comparables:
            for p in view.comparables.peers:
                self.session.add(ComparableCompany(
                    valuation_id=valuation_id, ticker=p.ticker, name=p.name,
                    payload=p.model_dump(mode="json"), source=p.source,
                    source_type="PUBLIC_API", source_url=p.source_url,
                ))
        for run in view.agents:
            self.session.add(_agent_row(valuation_id, run))
        if view.audit:
            self.session.add(AuditResultRow(
                valuation_id=valuation_id, status=view.audit.status.value,
                can_finalize=view.audit.can_finalize,
                checks=[c.model_dump(mode="json") for c in view.audit.checks],
                blocking_issues=view.audit.blocking_issues,
            ))
        for s in view.sources:
            self.session.add(SourceRow(
                valuation_id=valuation_id, external_id=s.id, name=s.name,
                source_type=s.source_type.value, url=s.url, retrieved_at=s.retrieved_at,
                description=s.description, metrics=s.metrics,
            ))
        self.session.flush()

    def list_valuations(self, limit: int = 20) -> list[Valuation]:
        return list(self.session.scalars(
            select(Valuation).order_by(Valuation.created_at.desc()).limit(limit)
        ))

    def commit(self) -> None:
        self.session.commit()


def _v(sv) -> float | None:
    if sv is None:
        return None
    return getattr(sv, "value", sv)


def _statement_row(period_id: str, stype: str, subset: dict) -> "FinancialStatement":
    from ..models.orm import FinancialStatement
    return FinancialStatement(
        period_id=period_id, statement_type=stype,
        payload={k: sv.model_dump(mode="json") for k, sv in subset.items()},
        source=next(iter(subset.values())).source,
        source_type=next(iter(subset.values())).source_type.value,
    )


def _assumption_row(valuation_id: str, a: Assumption) -> ValuationAssumption:
    return ValuationAssumption(
        valuation_id=valuation_id, key=a.key, label=a.label, group_name=a.group,
        value=a.value, currency=a.currency, unit=a.unit.value,
        source=a.source, source_url=a.source_url, source_type=a.source_type.value,
        confidence=None, is_user_override=a.is_override,
        historical_value=a.historical_value, model_estimate=a.model_estimate,
        user_value=a.user_value, status=a.status.value, note=a.note,
    )


def _agent_row(valuation_id: str, run: AgentRun) -> AgentRunRow:
    return AgentRunRow(
        valuation_id=valuation_id, agent=run.agent, agent_key=run.key,
        status=run.status, action=run.action, result=run.result,
        warnings=run.warnings, sources=run.sources, llm_used=run.llm_used,
        started_at=run.started_at, finished_at=run.finished_at, duration_ms=run.duration_ms,
    )


def _delete_where(model, column, value: str, session: Session) -> None:
    from sqlalchemy import delete
    session.execute(delete(model).where(column == value))


def load_view(valuation: Valuation) -> ValuationView | None:
    if not valuation.payload:
        return None
    return ValuationView.model_validate(valuation.payload)
