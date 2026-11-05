"""Valuation endpoints (spec §16).

`run` executes the LangGraph workflow. Assumption/scenario changes re-run the
same deterministic stages without re-ingestion and re-persist artifacts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.errors import AppError, MissingDataError, NotFoundError, ValidationError
from ..core.security import current_tenant, owner_matches
from ..data.providers.public_company import PublicCompanyProvider
from ..db.repository import Repository, load_view
from ..db.session import SessionLocal
from ..models.orm import Company as CompanyRow, Valuation as ValuationRow
from ..schemas.api import (
    AssumptionsRequest, RunValuationRequest, ScenarioPatchRequest,
    ValuationOptions,
)
from ..data.providers.base import MarketSnapshot
from ..schemas.common import SourceRecord
from ..schemas.company import CompanyInfo, PeriodData
from ..schemas.valuation import ValuationOptions, ValuationView
from ..services import assumptions as assumptions_svc
from ..services.engine import (
    PipelineContext, build_view, recompute_view,
)
from ..workflows.valuation_graph import run_valuation_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["valuation"])


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# context construction
# ---------------------------------------------------------------------------

def _load_company_context(session: Session, company_id: str) -> tuple[CompanyRow, PipelineContext]:
    row = session.get(CompanyRow, company_id)
    # Cross-tenant access is indistinguishable from a missing company.
    if row is None or not owner_matches(row.meta, current_tenant()):
        raise NotFoundError(f"Company {company_id} not found")
    meta = dict(row.meta or {})
    periods = [PeriodData.model_validate(p) for p in meta.get("periods", [])]
    # apply Data Review corrections (already merged into periods at patch time)
    company = CompanyInfo(
        id=row.id, name=row.name, ticker=row.ticker, exchange=row.exchange,
        cik=row.cik, currency=row.currency, industry=row.industry,
        sector=row.sector, sic_code=row.sic_code, is_public=row.is_public,
        source=meta.get("sources", [{}])[0].get("name", row.provider or "unknown"),
        source_url=None,
        retrieved_at=(meta.get("sources") or [{}])[0].get("retrieved_at"),
        provider=row.provider, notes=(meta.get("warnings") or [])[:6],
    )
    market = MarketSnapshot(**(meta.get("market") or {}))

    ctx = PipelineContext(
        company=company, periods=periods, market=market,
        options=ValuationOptions(peer_tickers=meta.get("peer_tickers", [])),
        excel_values=meta.get("excel_values", {}),
        debt_instruments=meta.get("debt_instruments", []),
        provider_missing=meta.get("missing", []),
        sources=[SourceRecord.model_validate(s) for s in meta.get("sources", [])],
    )
    return row, ctx


async def _ensure_peers(session: Session, company_row: CompanyRow, ctx: PipelineContext) -> None:
    """Fetch (once) comparable-company metrics for beta + multiples."""
    if not ctx.options.run_comparables or not ctx.company.is_public:
        return
    meta = dict(company_row.meta or {})
    cached = meta.get("peers")
    if cached:
        from ..schemas.valuation import PeerMetrics
        ctx.peers = [PeerMetrics.model_validate(p) for p in cached]
        return
    tickers = meta.get("peer_tickers") or []
    if not tickers:
        return
    provider = PublicCompanyProvider()
    peers, warnings = [], []
    for t in tickers[:4]:
        pm, w = await provider.fetch_peer(t)
        warnings.extend(w)
        if pm:
            peers.append(pm)
    ctx.peers = peers
    ctx.warnings.extend(warnings)
    meta["peers"] = [p.model_dump(mode="json") for p in peers]
    company_row.meta = meta
    session.flush()


# ---------------------------------------------------------------------------
# run / read
# ---------------------------------------------------------------------------

@router.post("/valuation/run")
async def run_valuation(body: RunValuationRequest, session: Session = Depends(get_db)):
    repo = Repository(session)
    try:
        company_row, ctx = _load_company_context(session, body.company_id)
        ctx.options = body.options
        ctx.overrides = dict(body.overrides or {})
        ctx.active_scenario = body.scenario
        await _ensure_peers(session, company_row, ctx)

        ctx = await run_valuation_workflow(ctx)

        valuation = repo.create_valuation(company_row.id, mode=company_row.meta.get("mode", "public"),
                                          overrides=ctx.overrides)
        view = build_view(ctx, valuation_id=valuation.id)
        repo.update_valuation_payload(valuation.id, view,
                                      status=view.summary.status,
                                      active_scenario=ctx.active_scenario,
                                      overrides=ctx.overrides)
        repo.replace_valuation_artifacts(valuation.id, view)
        session.commit()
        return view
    except AppError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.exception("valuation run failed")
        raise HTTPException(status_code=500, detail={"error": "internal_error",
                                                     "detail": str(exc)}) from exc


def _owned_valuation(session: Session, valuation_id: str) -> ValuationRow:
    """Load a valuation only if the caller owns its company."""
    row = session.get(ValuationRow, valuation_id)
    if row is not None:
        company = session.get(CompanyRow, row.company_id)
        if company is None or not owner_matches(company.meta, current_tenant()):
            row = None
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "not_found",
                                                     "detail": f"Valuation {valuation_id} not found"})
    return row


def _get_view(session: Session, valuation_id: str) -> tuple[ValuationRow, ValuationView]:
    row = _owned_valuation(session, valuation_id)
    view = load_view(row)
    if view is None:
        raise HTTPException(status_code=409, detail={"error": "not_ready",
                                                     "detail": "Valuation has no computed payload"})
    return row, view


@router.get("/valuation/{valuation_id}")
def get_valuation(valuation_id: str, session: Session = Depends(get_db)):
    _, view = _get_view(session, valuation_id)
    return view


def _section(valuation_id: str, attr: str, session: Session):
    _, view = _get_view(session, valuation_id)
    value = getattr(view, attr, None)
    if value is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "detail": f"Section '{attr}' not available for this valuation"})
    return value


@router.get("/valuation/{valuation_id}/financials")
def get_financials(valuation_id: str, session: Session = Depends(get_db)):
    _, view = _get_view(session, valuation_id)
    return {"historical": view.historical_periods, "historical_analysis": view.historical}


@router.get("/valuation/{valuation_id}/forecast")
def get_forecast(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "forecast", session)


@router.get("/valuation/{valuation_id}/wacc")
def get_wacc(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "wacc", session)


@router.get("/valuation/{valuation_id}/fcf")
def get_fcf(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "fcf", session)


@router.get("/valuation/{valuation_id}/dcf")
def get_dcf(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "dcf", session)


@router.get("/valuation/{valuation_id}/sensitivity")
def get_sensitivity(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "sensitivity", session)


@router.get("/valuation/{valuation_id}/comparables")
def get_comparables(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "comparables", session)


@router.get("/valuation/{valuation_id}/report")
def get_report(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "report", session)


@router.get("/valuation/{valuation_id}/audit")
def get_audit(valuation_id: str, session: Session = Depends(get_db)):
    return _section(valuation_id, "audit", session)


@router.get("/valuation/{valuation_id}/agents")
def get_agents(valuation_id: str, session: Session = Depends(get_db)):
    _, view = _get_view(session, valuation_id)
    return {"agents": view.agents}


@router.get("/valuation/{valuation_id}/sources")
def get_sources(valuation_id: str, session: Session = Depends(get_db)):
    _, view = _get_view(session, valuation_id)
    return {"sources": view.sources}


@router.get("/valuations")
def list_valuations(session: Session = Depends(get_db)):
    repo = Repository(session)
    out = []
    for v in repo.list_valuations():
        company = session.get(CompanyRow, v.company_id)
        if company is None or not owner_matches(company.meta, current_tenant()):
            continue
        payload = v.payload or {}
        summary = payload.get("summary", {})
        out.append({
            "id": v.id, "company_id": v.company_id, "status": v.status,
            "created_at": v.updated_at.isoformat() if v.updated_at else None,
            "name": (payload.get("company") or {}).get("name"),
            "ticker": (payload.get("company") or {}).get("ticker"),
            "implied_share_price": summary.get("implied_share_price"),
            "wacc": summary.get("wacc"),
        })
    return {"valuations": out}


# ---------------------------------------------------------------------------
# assumptions / scenarios
# ---------------------------------------------------------------------------

def _recompute(session: Session, row: ValuationRow, *, overrides: dict[str, float],
               clear: list[str], options: ValuationOptions | None,
               scenario: str | None, custom: dict[str, float] | None) -> ValuationView:
    view_old = load_view(row)
    company_row, ctx = _load_company_context(session, row.company_id)
    # keep prior run's options unless the request supplies new ones (no network)
    ctx.options = options or (view_old.options if view_old and view_old.options
                              else ValuationOptions())
    if view_old and view_old.comparables:
        ctx.peers = list(view_old.comparables.peers)

    prior_overrides = dict(row.overrides or {})
    prior_overrides.update(overrides)
    for k in clear:
        prior_overrides.pop(k, None)
    ctx.overrides = prior_overrides
    ctx.active_scenario = scenario or row.active_scenario or "base"
    ctx.custom_scenario = custom or {}
    # excel-provided values are already in meta; peers for beta need no refetch

    view = recompute_view(ctx, valuation_id=row.id)
    repo = Repository(session)
    repo.update_valuation_payload(row.id, view, status=view.summary.status,
                                  active_scenario=ctx.active_scenario,
                                  overrides=ctx.overrides)
    repo.replace_valuation_artifacts(row.id, view)
    session.commit()
    return view


@router.post("/valuation/{valuation_id}/assumptions")
def post_assumptions(valuation_id: str, body: AssumptionsRequest,
                     session: Session = Depends(get_db)):
    row = _owned_valuation(session, valuation_id)
    try:
        if not body.recompute:
            merged = dict(row.overrides or {})
            merged.update(body.overrides)
            for k in body.clear:
                merged.pop(k, None)
            row.overrides = merged
            session.commit()
            _, view = _get_view(session, valuation_id)
            return view
        return _recompute(session, row, overrides=body.overrides, clear=body.clear,
                          options=body.options, scenario=None, custom=None)
    except AppError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc


@router.post("/valuation/{valuation_id}/scenarios")
def post_scenarios(valuation_id: str, body: ScenarioPatchRequest,
                   session: Session = Depends(get_db)):
    row = _owned_valuation(session, valuation_id)
    try:
        if not body.recompute:
            row.active_scenario = body.active
            row.payload = {**(row.payload or {}),
                           "summary": {**(row.payload or {}).get("summary", {}),
                                       "active_scenario": body.active}}
            session.commit()
            _, view = _get_view(session, valuation_id)
            return view
        return _recompute(session, row, overrides={}, clear=[],
                          options=None, scenario=body.active,
                          custom=body.overrides if body.active == "custom" else None)
    except AppError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
