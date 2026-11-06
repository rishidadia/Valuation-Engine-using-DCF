"""Company endpoints: Mode A (Excel upload), Mode B (public ticker), data review."""
from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..agents import financial_data as data_agent
from ..core.config import settings
from ..core.errors import AppError, ExcelValidationError, ProviderError
from ..core.security import current_tenant, owner_matches
from ..data.excel_template import build_template
from ..data.providers import ExcelProvider, PublicCompanyProvider, get_provider
from ..data.providers.fred import FredRiskFreeProvider
from ..db.repository import Repository
from ..db.session import SessionLocal
from ..models.orm import Company as CompanyRow
from ..schemas.api import IngestResponse, MetricOverride, MetricsPatchRequest, PublicCompanyBody
from ..schemas.common import METRIC_LABELS, SourceRecord, SourceType, SourcedValue, Unit, ValueStatus
from ..schemas.company import CompanyInfo, DataReview, DataReviewRow, PeriodData

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["company"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Mode B — public company
# ---------------------------------------------------------------------------

@router.post("/company/public", response_model=IngestResponse)
async def ingest_public(body: PublicCompanyBody, session: Session = Depends(_session)):
    provider = PublicCompanyProvider()
    try:
        payload, runs, _ = await data_agent.ingest(
            provider, ticker=body.ticker, market=body.market,
            include_comparables=body.include_comparables,
            peer_tickers=body.peer_tickers,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc

    if body.name:
        payload.company.name = body.name
    if body.exchange:
        payload.company.exchange = body.exchange

    # risk-free rate also applies to Excel mode; try here for public mode
    repo = Repository(session)
    company = _persist(repo, payload, mode="public",
                       excel_values={}, debt_instruments=[],
                       peer_tickers=[p for p in (payload.preview[0].get("peers") if payload.preview else []) or []],
                       owner=current_tenant())
    review = _build_review(payload.company, payload.periods, payload.missing, payload.warnings)
    session.commit()
    return IngestResponse(company_id=company.id, mode="public", review=review,
                          warnings=payload.warnings,
                          agents=[r.model_dump(mode="json") for r in runs])


# ---------------------------------------------------------------------------
# Mode A — Excel upload
# ---------------------------------------------------------------------------

@router.post("/company/upload", response_model=IngestResponse)
async def ingest_excel(
    file: UploadFile = File(...),
    company_name: str | None = Form(default=None),
    currency: str | None = Form(default=None),
    fiscal_year_end: str | None = Form(default=None),
    session: Session = Depends(_session),
):
    original = file.filename or "workbook.xlsx"
    safe = _SAFE_NAME.sub("_", Path(original).name)[:120] or "workbook.xlsx"
    if not safe.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail=ExcelValidationError(
            "Only .xlsx uploads are accepted.", hint="Convert the workbook to .xlsx and retry."
        ).to_dict())

    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=422, detail=ExcelValidationError(
            f"File too large ({len(data):,} bytes; limit {settings.max_upload_bytes:,})."
        ).to_dict())

    provider = ExcelProvider()
    tmp_dir = Path(tempfile.mkdtemp(prefix="dcf_upload_"))
    path = tmp_dir / safe
    try:
        path.write_bytes(data)
        payload, runs, mapping = await data_agent.ingest(
            provider, path=path, original_name=safe, company_name=company_name,
            currency=currency, fiscal_year_end=fiscal_year_end)
    except AppError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()) from exc
    finally:
        try:
            path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass

    # Market-level input: the retrieved 10Y Treasury is written into the market
    # snapshot (not just a warning) so WACC uses it instead of the static 4% default.
    try:
        obs = await FredRiskFreeProvider().latest_10y()
        payload.market.risk_free_rate = obs["rate"]
        payload.market.risk_free_source = (
            f"FRED DGS10 as of {obs['as_of']} ({obs['rate']:.2%})"
        )
        payload.sources.append(SourceRecord(
            id="fred-dgs10",
            name=f"FRED DGS10 — 10Y Treasury ({obs['as_of']})",
            source_type=SourceType.PUBLIC_API,
            url="https://fred.stlouisfed.org/series/DGS10",
            retrieved_at=datetime.now(timezone.utc).date(),
            description="Risk-free rate proxy: 10-year US Treasury constant-maturity yield.",
            metrics=["risk_free_rate"],
        ))
        payload.warnings.append(
            f"Risk-free rate retrieved from FRED DGS10: {obs['rate']:.2%} "
            f"({obs['as_of']}) and stored as the market risk-free rate; "
            "override it on the Assumptions page to change it."
        )
    except Exception:  # noqa: BLE001 — optional enrichment
        payload.warnings.append("Risk-free rate provider unavailable — set it manually "
                                "on the Assumptions page (labelled model default until then).")

    company_hints = {"name": company_name} if company_name else {}
    payload.company.name = company_hints.get("name") or payload.company.name

    repo = Repository(session)
    company = _persist(repo, payload, mode="excel",
                       excel_values=getattr(provider, "assumption_values", {}),
                       debt_instruments=getattr(provider, "debt_instruments", []),
                       mapping_notes=[m.model_dump(mode="json") for m in getattr(provider, "mapping_notes", [])],
                       peer_tickers=[], owner=current_tenant())
    review = _build_review(payload.company, payload.periods, payload.missing, payload.warnings)
    session.commit()
    return IngestResponse(company_id=company.id, mode="excel", review=review,
                          warnings=payload.warnings,
                          agents=[r.model_dump(mode="json") for r in runs])


@router.get("/company/template")
def download_template():
    buf = build_template()
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="dcf_labs_template.xlsx"'},
    )


# ---------------------------------------------------------------------------
# Company read + Data Review corrections
# ---------------------------------------------------------------------------

@router.get("/company/{company_id}")
def get_company(company_id: str, session: Session = Depends(_session)):
    repo = Repository(session)
    row = repo.get_company(company_id)
    # Cross-tenant reads are reported as "not found" so existence is not leaked.
    if row is None or not owner_matches(row.meta, current_tenant()):
        raise HTTPException(status_code=404, detail={"error": "not_found",
                                                     "detail": f"Company {company_id} not found"})
    meta = row.meta or {}
    company = _row_to_company(row, meta)
    periods = [PeriodData.model_validate(p) for p in meta.get("periods", [])]
    review = _build_review(company, periods, meta.get("missing", []),
                           meta.get("warnings", []))
    return {"company": company, "review": review,
            "mapping_notes": meta.get("mapping_notes", []),
            "excel_values": meta.get("excel_values", {}),
            "debt_instruments": meta.get("debt_instruments", [])}


@router.patch("/company/{company_id}/metrics")
def patch_metrics(company_id: str, body: MetricsPatchRequest,
                  session: Session = Depends(_session)):
    """Data Review corrections: user fixes a value or fills a missing metric."""
    row = session.get(CompanyRow, company_id)
    if row is None or not owner_matches(row.meta, current_tenant()):
        raise HTTPException(status_code=404, detail={"error": "not_found",
                                                     "detail": "Company not found"})
    meta = dict(row.meta or {})
    overrides = dict(meta.get("metric_overrides", {}))
    excel_values = dict(meta.get("excel_values", {}))
    periods = [PeriodData.model_validate(p) for p in meta.get("periods", [])]
    period_map = {p.period: p for p in periods}

    for ov in body.overrides:
        target_period = ov.period or (periods[-1].period if periods else None)
        if target_period not in period_map:
            raise HTTPException(status_code=422, detail={
                "error": "validation_error",
                "detail": f"Period {target_period} not found",
                "hint": f"Available: {', '.join(period_map)}",
            })
        overrides.setdefault(target_period, {})
        p = period_map[target_period]
        if ov.value is None:
            # clearing removes the stored metric AND any workbook-derived value
            overrides[target_period].pop(ov.metric, None)
            p.metrics.pop(ov.metric, None)
            excel_values.pop(ov.metric, None)
        else:
            if ov.metric not in METRIC_LABELS:
                raise HTTPException(status_code=422, detail={
                    "error": "validation_error",
                    "detail": f"Unknown metric '{ov.metric}'",
                    "hint": f"Known metrics: {', '.join(sorted(METRIC_LABELS))}",
                })
            overrides[target_period][ov.metric] = ov.value
            p = period_map[target_period]
            p.metrics[ov.metric] = SourcedValue(
                value=ov.value,
                unit=Unit.COUNT if ov.metric == "shares_outstanding" else Unit.CURRENCY,
                period=target_period, source_type=SourceType.USER_INPUT,
                source="User correction on Data Review page",
                retrieved_at=datetime.now(timezone.utc).date(),
                status=ValueStatus.USER_DATA, is_user_override=True,
            )
            if ov.metric in excel_values:
                excel_values[ov.metric] = ov.value
    meta["periods"] = [p.model_dump(mode="json") for p in periods]
    meta["metric_overrides"] = overrides
    meta["excel_values"] = excel_values
    row.meta = meta
    session.commit()

    company = _row_to_company(row, meta)
    return _build_review(company, periods, meta.get("missing", []), meta.get("warnings", []))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _persist(repo: Repository, payload, *, mode: str, excel_values: dict,
             debt_instruments: list[dict], peer_tickers: list[str] | None = None,
             mapping_notes: list | None = None, owner: str | None = None):
    company_row = repo.save_company(payload.company)
    meta = dict(company_row.meta or {})
    meta.update({
        "owner": owner or meta.get("owner"),
        "mode": mode,
        "periods": [p.model_dump(mode="json") for p in payload.periods],
        "market": payload.market.model_dump(mode="json"),
        "missing": payload.missing,
        "warnings": payload.warnings,
        "sources": [s.model_dump(mode="json") for s in payload.sources],
        "excel_values": excel_values,
        "debt_instruments": debt_instruments,
        "mapping_notes": mapping_notes or [],
        "peer_tickers": peer_tickers or [],
        "metric_overrides": meta.get("metric_overrides", {}),
    })
    company_row.meta = meta
    repo.save_periods(company_row.id, payload.periods)
    repo.save_market(company_row.id, payload.market.model_dump(mode="json"))
    if debt_instruments:
        repo.save_debt_instruments(company_row.id, debt_instruments)
    return company_row


def _row_to_company(row, meta: dict) -> CompanyInfo:
    return CompanyInfo(
        id=row.id, name=row.name, ticker=row.ticker, exchange=row.exchange,
        cik=row.cik, currency=row.currency, industry=row.industry,
        sector=row.sector, sic_code=row.sic_code, is_public=row.is_public,
        source=meta.get("sources", [{}])[0].get("name", row.provider or "unknown"),
        provider=row.provider, notes=(meta.get("warnings") or [])[:6],
    )


def _build_review(company: CompanyInfo, periods: list[PeriodData],
                  missing: list[str], warnings: list[str]) -> DataReview:
    rows: list[DataReviewRow] = []
    latest = periods[-1] if periods else None
    if latest:
        for key, sv in latest.metrics.items():
            rows.append(DataReviewRow(
                key=key, field=METRIC_LABELS.get(key, key.replace("_", " ").title()),
                value=sv.value, display=_fmt_value(sv.value, key, latest.currency),
                unit=sv.unit.value, currency=sv.currency or latest.currency,
                period=latest.period, source=sv.source, source_type=sv.source_type,
                status=sv.status, critical=key in ("revenue", "ebit", "total_debt", "cash"),
                note=sv.note, cell_ref=sv.cell_ref,
            ))
    for key in missing:
        if latest and key in latest.metrics:
            continue
        rows.append(DataReviewRow(
            key=key, field=METRIC_LABELS.get(key, key.replace("_", " ").title()),
            value=None, display=None, unit="count" if key == "shares_outstanding" else "currency",
            period=latest.period if latest else None,
            source="No source — manual entry required", source_type=SourceType.MODEL_ASSUMPTION,
            status=ValueStatus.MISSING, critical=True,
            note="Missing values are never guessed; enter one to continue.",
        ))
    return DataReview(company=company, rows=rows, missing_critical=missing,
                      warnings=warnings, periods=[p.period for p in periods])


def _fmt_value(v: float | None, key: str, currency: str | None) -> str:
    if v is None:
        return "—"
    if key == "shares_outstanding":
        return f"{v:,.0f}"
    return f"{v:,.0f}"
