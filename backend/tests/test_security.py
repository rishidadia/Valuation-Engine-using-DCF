"""Optional API-key protection and tenant isolation.

With no keys configured the app stays open for local use. With DCF_API_KEYS set,
every /api route except health requires X-API-Key, and each key only sees the
companies and valuations it created.
"""
import io

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.data.excel_template import build_template
from app.main import app

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def auth():
    settings.dcf_api_keys = "key-a,key-b"
    try:
        yield
    finally:
        settings.dcf_api_keys = ""


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, key: str, name: str) -> str:
    r = client.post(
        "/api/company/upload",
        headers={"X-API-Key": key},
        files={"file": ("model.xlsx", build_template().getvalue(), XLSX)},
        data={"company_name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["company_id"]


def test_health_stays_public_when_auth_enabled(client, auth):
    assert client.get("/api/health").status_code == 200


def test_api_requires_key_when_configured(client, auth):
    r = client.get("/api/valuations", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 401
    # CORS stays outermost so a browser can read the 401 from a cross origin.
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert client.get("/api/valuations", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/api/valuations", headers={"X-API-Key": "key-a"}).status_code == 200


def test_open_when_no_keys_configured(client):
    assert client.get("/api/valuations").status_code == 200


def test_company_is_isolated_per_key(client, auth):
    company_id = _upload(client, "key-a", "Isolated Co")

    assert client.get(f"/api/company/{company_id}",
                      headers={"X-API-Key": "key-a"}).status_code == 200
    assert client.get(f"/api/company/{company_id}",
                      headers={"X-API-Key": "key-b"}).status_code == 404
    assert client.patch(f"/api/company/{company_id}/metrics",
                        headers={"X-API-Key": "key-b"},
                        json={"overrides": []}).status_code == 404


def test_valuation_list_and_read_are_isolated(client, auth):
    company_id = _upload(client, "key-a", "Valuation Isolation Co")
    run = client.post("/api/valuation/run",
                      headers={"X-API-Key": "key-a"},
                      json={"company_id": company_id,
                            "options": {"run_comparables": False,
                                        "run_sensitivity": False}})
    assert run.status_code == 200, run.text
    vid = run.json()["summary"]["id"]

    mine = client.get("/api/valuations", headers={"X-API-Key": "key-a"}).json()["valuations"]
    assert any(v["id"] == vid for v in mine)

    theirs = client.get("/api/valuations", headers={"X-API-Key": "key-b"}).json()["valuations"]
    assert all(v["id"] != vid for v in theirs)
    assert client.get(f"/api/valuation/{vid}",
                      headers={"X-API-Key": "key-b"}).status_code == 404
    assert client.get(f"/api/valuation/{vid}",
                      headers={"X-API-Key": "key-a"}).status_code == 200
