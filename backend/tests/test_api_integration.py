"""End-to-end API tests: both entry modes, full LangGraph run, overrides, scenarios.

The public-company tests hit live keyless APIs (SEC/Yahoo/FRED) and are
skipped automatically when offline.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _network_available() -> bool:
    import httpx
    try:
        r = httpx.get("https://www.sec.gov/files/company_tickers.json", timeout=8,
                      headers={"User-Agent": "dcf-labs test"})
        return r.status_code == 200
    except Exception:
        return False


needs_network = pytest.mark.skipif(not _network_available(),
                                   reason="external data providers unreachable")


@needs_network
def test_public_company_full_flow(client):
    # 1) ingest
    r = client.post("/api/company/public", json={"ticker": "AAPL", "include_comparables": True})
    assert r.status_code == 200, r.text
    data = r.json()
    company_id = data["company_id"]
    review = data["review"]
    assert review["company"]["ticker"] == "AAPL"
    fields = {row["field"] for row in review["rows"]}
    assert "Revenue" in fields
    statuses = {row["status"] for row in review["rows"]}
    assert "Retrieved" in statuses

    # 2) run valuation through the LangGraph workflow
    r = client.post("/api/valuation/run", json={
        "company_id": company_id,
        "options": {"beta_method": "market", "run_comparables": True},
    })
    assert r.status_code == 200, r.text
    view = r.json()
    vid = view["summary"]["id"]

    # summary sanity
    s = view["summary"]
    assert s["status"] in ("complete", "blocked")
    assert s["wacc"] and 0.02 < s["wacc"] < 0.30
    assert s["implied_share_price"] and s["implied_share_price"] > 0
    assert s["enterprise_value"] and s["enterprise_value"] > 0

    # all 12 agents reported
    agent_keys = [a["key"] for a in view["agents"]]
    for expected in ("research", "data", "validation", "historical", "forecast",
                     "wacc", "fcf", "dcf", "sensitivity", "comparables", "audit", "report"):
        assert expected in agent_keys, f"missing agent {expected}: {agent_keys}"
    assert all(a["status"] in ("success", "warning", "failed", "skipped") for a in view["agents"])
    # no chain-of-thought fields exposed
    for a in view["agents"]:
        assert "reasoning" not in a and "chain_of_thought" not in a

    # audit
    assert view["audit"]["status"] in ("PASS", "WARNING", "FAIL")
    assert len(view["audit"]["checks"]) >= 10

    # every FCF year shows components
    y1 = view["fcf"]["years"][0]
    for key in ("ebit", "tax_expense", "nopat", "da", "capex", "change_nwc", "fcf", "discount_factor"):
        assert key in y1 and y1[key] is not None
    # FCF identity holds
    assert y1["fcf"]["value"] == pytest.approx(
        y1["nopat"]["value"] + y1["da"]["value"] - y1["capex"]["value"] - y1["change_nwc"]["value"],
        rel=1e-9)

    # both terminal methods reported (or explicitly blocked)
    assert len(view["dcf"]["terminal_methods"]) == 2

    # sensitivity + scenarios present
    assert len(view["sensitivity"]["tables"]) >= 2
    assert len(view["scenarios"]["scenarios"]) >= 3

    # comparables fetched live (suggested peers exist for AAPL)
    assert view["comparables"]["status"] in ("ok", "insufficient_data")

    # traceability: beta carries a source
    beta = next(a for a in view["assumptions"] if a["key"] == "beta")
    assert beta["source_type"] in ("PUBLIC_API", "MODEL_CALCULATION", "USER_OVERRIDE")
    assert beta["source"]

    # 3) user override propagates and is visible
    base_price = s["implied_share_price"]
    r = client.post(f"/api/valuation/{vid}/assumptions",
                    json={"overrides": {"revenue_growth": 0.12}})
    assert r.status_code == 200, r.text
    view2 = r.json()
    g = next(a for a in view2["assumptions"] if a["key"] == "revenue_growth")
    assert g["source_type"] == "USER_OVERRIDE"
    assert g["status"] == "Override"
    assert g["user_value"] == pytest.approx(0.12)
    assert g["value"] == pytest.approx(0.12)
    assert view2["summary"]["implied_share_price"] != base_price

    # invalid override rejected explicitly
    r = client.post(f"/api/valuation/{vid}/assumptions",
                    json={"overrides": {"revenue_growth": 9.0}})
    assert r.status_code == 422
    assert "outside plausible range" in r.text

    # 4) scenarios
    r = client.post(f"/api/valuation/{vid}/scenarios", json={"active": "bear"})
    assert r.status_code == 200, r.text
    view3 = r.json()
    bear = next(x for x in view3["scenarios"]["scenarios"] if x["name"] == "bear")
    base = next(x for x in view3["scenarios"]["scenarios"] if x["name"] == "base")
    assert bear["implied_share_price"] < base["implied_share_price"]

    # 5) section endpoints
    for section in ("financials", "forecast", "wacc", "fcf", "dcf",
                    "sensitivity", "report", "audit", "agents", "sources"):
        r = client.get(f"/api/valuation/{vid}/{section}")
        assert r.status_code == 200, f"{section}: {r.text}"

    # report markdown contains the disclaimer
    md = client.get(f"/api/valuation/{vid}/report").json()["markdown"]
    assert "highly sensitive to assumptions" in md
    assert "Data Sources" in md


@needs_network
def test_invalid_ticker_is_explicit(client):
    r = client.post("/api/company/public", json={"ticker": "NOTAREALTICKERZZ"})
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error"] in ("ticker_not_found", "provider_error")


def test_excel_template_download(client):
    r = client.get("/api/company/template")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert len(r.content) > 5000


def test_excel_upload_and_private_valuation(client):
    """Mode A: upload template, correct values, run a private-company valuation."""
    tpl = client.get("/api/company/template").content
    r = client.post("/api/company/upload",
                    files={"file": ("acme.xlsx", tpl,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"company_name": "Acme Manufacturing"})
    assert r.status_code == 200, r.text
    data = r.json()
    company_id = data["company_id"]
    assert data["review"]["company"]["name"] == "Acme Manufacturing"
    assert data["review"]["periods"], "expected detected periods"

    # private company: needs beta + target structure to run WACC
    r = client.post("/api/valuation/run", json={
        "company_id": company_id,
        "overrides": {"beta": 1.10, "share_price": 24.50},
        "options": {"capital_structure_method": "target", "run_comparables": False},
    })
    assert r.status_code == 200, r.text
    view = r.json()
    vid = view["summary"]["id"]
    assert view["summary"]["implied_share_price"] is not None
    # Excel provenance preserved
    hist = view["historical_periods"][-1]
    rev = hist["metrics"]["revenue"]
    assert rev["source_type"] == "UPLOADED_EXCEL"
    assert rev["cell_ref"]

    # missing shares blocks per-share price but not the valuation —
    # here template has shares, so price exists; now clear it via data review
    r = client.patch(f"/api/company/{company_id}/metrics",
                     json={"overrides": [{"metric": "shares_outstanding", "value": None},
                                         {"metric": "revenue", "value": 15_000_000}]})
    assert r.status_code == 200, r.text
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["revenue"]["source_type"] == "USER_INPUT"
    assert rows["revenue"]["value"] == 15_000_000


def test_missing_shares_never_fabricated(client):
    tpl = client.get("/api/company/template").content
    r = client.post("/api/company/upload",
                    files={"file": ("acme2.xlsx", tpl,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"company_name": "NoShares Inc"})
    company_id = r.json()["company_id"]
    # remove shares
    client.patch(f"/api/company/{company_id}/metrics",
                 json={"overrides": [{"metric": "shares_outstanding", "value": None}]})
    r = client.post("/api/valuation/run", json={
        "company_id": company_id,
        "overrides": {"beta": 1.0},
        "options": {"capital_structure_method": "target", "run_comparables": False},
    })
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["summary"]["implied_share_price"] is None  # not invented
    assert view["summary"]["equity_value"] is not None  # equity still computed
