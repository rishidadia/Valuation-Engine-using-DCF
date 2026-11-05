"""Excel mode must use the FRED risk-free rate it retrieves.

The route used to append the FRED observation to the warnings only, so the WACC
stage could silently fall back to the static 4% model default. The rate now
lands in the market snapshot with its source and date, and — because user input
outranks retrieved data — a risk-free entry typed in the workbook still wins.
"""
import asyncio
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api import routes_company
from app.data.excel_template import build_template
from app.db.session import SessionLocal
from app.main import app
from app.models.orm import Company
from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.schemas.company import PeriodData
from app.services.assumptions import build_assumptions
from app.services.historical import analyze
from app.data.providers.base import MarketSnapshot

RATE = 0.0425


def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.USER_INPUT, status=ValueStatus.USER_DATA)


def _periods() -> list[PeriodData]:
    out, rev = [], 100e6
    for i, y in enumerate(range(2024, 2026)):
        if i:
            rev *= 1.08
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 12, 31), metrics={
            "revenue": _sv(rev), "cogs": _sv(rev * .6), "gross_profit": _sv(rev * .4),
            "ebit": _sv(rev * .18), "ebt": _sv(rev * .17),
            "income_tax_expense": _sv(rev * .04), "net_income": _sv(rev * .13),
            "da": _sv(rev * .03), "capex": _sv(rev * .04), "change_nwc": _sv(rev * .01),
            "cash": _sv(50e6), "total_debt": _sv(120e6),
            "shares_outstanding": _sv(10e6, Unit.COUNT),
        }))
    return out


def _assumption(values, key: str):
    return next(a for a in values if a.key == key)


def test_market_risk_free_rate_used_when_workbook_does_not_override():
    market = MarketSnapshot(risk_free_rate=RATE, risk_free_source=f"FRED DGS10 as of 2026-10-30 ({RATE:.2%})")
    assumptions = build_assumptions(analyze(_periods(), private=True), _periods(), market,
                                    private=True, excel_values={"beta": 1.1})
    rf = _assumption(assumptions, "risk_free_rate")
    assert rf.value == pytest.approx(RATE)
    assert rf.source_type is SourceType.PUBLIC_API
    assert "FRED" in rf.source


def test_workbook_risk_free_rate_outranks_retrieved_rate():
    market = MarketSnapshot(risk_free_rate=RATE, risk_free_source="FRED DGS10")
    assumptions = build_assumptions(analyze(_periods(), private=True), _periods(), market,
                                    private=True, excel_values={"risk_free_rate": 0.038})
    rf = _assumption(assumptions, "risk_free_rate")
    assert rf.value == pytest.approx(0.038)
    assert rf.source_type is SourceType.USER_INPUT


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_upload_uses_fred_rate_end_to_end(client, monkeypatch):
    async def fake_latest(self):  # noqa: ARG001
        return {"rate": RATE, "as_of": "2026-10-30", "series": "DGS10",
                "label": "10-Year US Treasury Yield"}

    monkeypatch.setattr(routes_company.FredRiskFreeProvider, "latest_10y", fake_latest)

    # Template minus its "Risk-Free Rate" assumption row, so FRED is not masked
    # by a workbook value (workbook input still has higher precedence by design).
    wb = load_workbook(io.BytesIO(build_template().getvalue()))
    ws = wb["Assumptions"]
    for row in list(ws.iter_rows(min_row=5, max_row=40)):
        if isinstance(row[0].value, str) and row[0].value.lower().startswith("risk-free"):
            ws.delete_rows(row[0].row)
            break
    buf = io.BytesIO()
    wb.save(buf)

    r = client.post("/api/company/upload",
                    files={"file": ("model.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"company_name": "FRED Check Co"})
    assert r.status_code == 200, r.text
    company_id = r.json()["company_id"]

    session = SessionLocal()
    try:
        meta = dict(session.get(Company, company_id).meta or {})
    finally:
        session.close()
    assert meta["market"]["risk_free_rate"] == pytest.approx(RATE)
    assert "FRED" in (meta["market"]["risk_free_source"] or "")
    assert any(s["id"] == "fred-dgs10" for s in meta["sources"])

    # the valuation actually consumes it
    run = client.post("/api/valuation/run", json={"company_id": company_id,
                                                  "options": {"run_comparables": False,
                                                              "run_sensitivity": False}})
    assert run.status_code == 200, run.text
    view = run.json()
    rf = next(a for a in view["assumptions"] if a["key"] == "risk_free_rate")
    assert rf["value"] == pytest.approx(RATE)
    assert "FRED" in rf["source"]
