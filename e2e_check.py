"""Live E2E pipeline checks against http://127.0.0.1:8000.

Usage: python e2e_check.py [public|excel|all]   (default: all)
Prints PASS/FAIL per check; exit code 1 if any FAIL.
"""
from __future__ import annotations

import io
import sys
import traceback

import httpx
from openpyxl import load_workbook

BASE = "http://127.0.0.1:8000"
C = httpx.Client(base_url=BASE, timeout=httpx.Timeout(180.0, connect=10.0))

PASS: list[str] = []
FAIL: list[str] = []


def check(case: str, name: str, cond: bool, detail: str = "") -> bool:
    tag = f"[{case}] {name}"
    if cond:
        PASS.append(tag)
        print(f"  PASS  {tag}" + (f"  ({detail})" if detail else ""), flush=True)
    else:
        FAIL.append(tag)
        print(f"  FAIL  {tag}  ({detail})", flush=True)
    return bool(cond)


def dump_error(case: str, r: httpx.Response) -> None:
    body = r.text[:800]
    print(f"  ERROR [{case}] HTTP {r.status_code}: {body}", flush=True)


# --------------------------------------------------------------------------
# Mode B — public companies
# --------------------------------------------------------------------------

PUBLIC_CASES = [
    ("MSFT", ["GOOGL", "AAPL"]),   # D&A split across component tags (original bug)
    ("GOOGL", ["MSFT", "META"]),   # no dei shares tag; revenue across concepts
    ("AAPL", ["MSFT", "GOOGL"]),   # combined D&A concept
    ("NVDA", ["AMD", "QCOM"]),     # different filer style
    ("JPM", ["BAC", "WFC"]),       # financial-sector tagging
    ("JNJ", ["PFE", "MRK"]),       # healthcare, different fiscal calendar
]

SECTIONS = ("financials", "forecast", "wacc", "fcf", "dcf", "sensitivity",
            "report", "audit", "agents", "sources", "comparables")


def public_case(ticker: str, peers: list[str]) -> None:
    case = f"public:{ticker}"
    print(f"\n=== {case} (peers: {','.join(peers)}) ===", flush=True)

    r = C.post("/api/company/public", json={"ticker": ticker, "peer_tickers": peers})
    if not check(case, "ingest 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    cid = r.json()["company_id"]

    r = C.post("/api/valuation/run",
               json={"company_id": cid, "options": {"run_comparables": True}})
    if not check(case, "run 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    view = r.json()
    vid = view["summary"]["id"]
    status = view["summary"]["status"]
    blocked = view["summary"].get("blocked_reasons") or []
    check(case, "status complete", status == "complete",
          f"status={status} blocked={blocked}")

    # da_pct — the originally reported bug
    da = next((a for a in view["assumptions"] if a["key"] == "da_pct"), None)
    check(case, "da_pct present", da is not None and da["value"] is not None,
          f"value={None if da is None else da['value']} source={None if da is None else da.get('source')}")

    # forecast runs, 5 years, no spurious override tag
    years = view.get("forecast", {}).get("years") or []
    check(case, "forecast years", len(years) >= 5, f"n={len(years)}")
    notes = " | ".join(str(y.get("note") or "") for y in years)
    check(case, "no spurious [USER OVERRIDE]", "[USER OVERRIDE]" not in notes,
          notes[:160])

    # valuation numbers
    s = view["summary"]
    check(case, "implied price", (s.get("implied_share_price") or 0) > 0,
          f"price={s.get('implied_share_price')} market={s.get('current_share_price')}")
    check(case, "wacc in range", s.get("wacc") and 0.02 < s["wacc"] < 0.30,
          f"wacc={s.get('wacc')}")
    check(case, "vs-market comparison present",
          s.get("current_share_price") is not None
          and s.get("upside_downside") is not None,
          f"upside={s.get('upside_downside')}")

    # audit
    audit = view["audit"]
    check(case, "audit finalizable", audit.get("can_finalize") is True,
          f"status={audit.get('status')} issues={len(audit.get('issues') or audit.get('checks') or [])}")

    # comparables
    comp = view.get("comparables") or {}
    check(case, "comparables ok", comp.get("status") in ("ok", "insufficient_data"),
          f"status={comp.get('status')} n={len(comp.get('rows') or [])}")

    # every section endpoint
    bad = []
    for sec in SECTIONS:
        rr = C.get(f"/api/valuation/{vid}/{sec}")
        if rr.status_code != 200:
            bad.append(f"{sec}:{rr.status_code}")
    check(case, "all section endpoints 200", not bad, ",".join(bad))

    # report: conclusion first, market comparison present
    rr = C.get(f"/api/valuation/{vid}/report")
    if check(case, "report 200", rr.status_code == 200):
        md = rr.json().get("markdown", "")
        i_bottom = md.find("Bottom Line")
        i_sources = md.find("Data Sources")
        check(case, "report verdict first", 0 <= i_bottom < i_sources,
              f"bottom@{i_bottom} sources@{i_sources}")
        check(case, "report compares to market",
              "market price" in md.lower() or "market value" in md.lower())

    # sensitivity + scenarios
    check(case, "sensitivity tables >= 2", len(view["sensitivity"]["tables"]) >= 2)
    check(case, "scenarios >= 3", len(view["scenarios"]["scenarios"]) >= 3)

    print(f"  -> vid={vid} price={s.get('implied_share_price')} "
          f"market={s.get('current_share_price')} "
          f"upside={None if s.get('upside_downside') is None else round(s['upside_downside'] * 100, 1)}%", flush=True)


def public_suite() -> None:
    # negative control first: unknown ticker must be an explicit 404
    r = C.post("/api/company/public", json={"ticker": "NOTAREALTICKERZZ"})
    check("public:neg", "unknown ticker 404", r.status_code == 404, f"HTTP {r.status_code}")
    for ticker, peers in PUBLIC_CASES:
        try:
            public_case(ticker, peers)
        except Exception:
            FAIL.append(f"public:{ticker} exception")
            print(f"  EXCEPTION [{ticker}]:", flush=True)
            traceback.print_exc()


# --------------------------------------------------------------------------
# Mode A — private Excel uploads
# --------------------------------------------------------------------------

def _template() -> bytes:
    r = C.get("/api/company/template")
    r.raise_for_status()
    return r.content


def _upload(wb_bytes: bytes, name: str) -> httpx.Response:
    return C.post("/api/company/upload",
                  files={"file": (name.lower().replace(" ", "_") + ".xlsx", wb_bytes,
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                  data={"company_name": name})


def _run(cid: str, overrides: dict | None = None, options: dict | None = None):
    body: dict = {"company_id": cid}
    if overrides:
        body["overrides"] = overrides
    if options:
        body["options"] = options
    return C.post("/api/valuation/run", json=body)


def excel_default() -> None:
    """Template as shipped (sample numbers + Assumptions sheet filled)."""
    case = "excel:default"
    print(f"\n=== {case} ===", flush=True)
    r = _upload(_template(), "Acme Manufacturing")
    if not check(case, "upload 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    cid = r.json()["company_id"]
    check(case, "periods detected", bool(r.json()["review"].get("periods")))

    # first attempt: rely entirely on workbook-provided assumptions (beta 1.1 etc.)
    r = _run(cid, options={"capital_structure_method": "target", "run_comparables": False})
    if not check(case, "run 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    view = r.json()
    s = view["summary"]
    status = s["status"]
    if status != "complete":
        # private companies may still need an explicit beta — retry and note it
        print(f"  note: first run status={status} blocked={s.get('blocked_reasons')}; "
              "retrying with beta override", flush=True)
        r = _run(cid, overrides={"beta": 1.10, "share_price": 24.50},
                 options={"capital_structure_method": "target", "run_comparables": False})
        view = r.json()
        s = view["summary"]
        status = s["status"]
    check(case, "status complete", status == "complete",
          f"status={status} blocked={s.get('blocked_reasons')}")

    da = next((a for a in view["assumptions"] if a["key"] == "da_pct"), None)
    check(case, "da_pct present", da is not None and da["value"] is not None,
          f"value={None if da is None else da['value']}")
    years = view.get("forecast", {}).get("years") or []
    check(case, "forecast >= 5y", len(years) >= 5, f"n={len(years)}")
    check(case, "implied price", (s.get("implied_share_price") or 0) > 0,
          f"price={s.get('implied_share_price')}")
    check(case, "audit finalizable", view["audit"].get("can_finalize") is True,
          f"status={view['audit'].get('status')}")

    # Excel provenance survives into historical periods
    hist = (view.get("historical_periods") or [])
    if hist:
        rev = hist[-1]["metrics"].get("revenue") or {}
        check(case, "excel provenance", rev.get("source_type") == "UPLOADED_EXCEL",
              f"source_type={rev.get('source_type')} cell={rev.get('cell_ref')}")
    else:
        check(case, "excel provenance", False, "no historical_periods in view")

    vid = s["id"]
    rr = C.get(f"/api/valuation/{vid}/report")
    if check(case, "report 200", rr.status_code == 200):
        md = rr.json().get("markdown", "")
        check(case, "report verdict first", md.find("Bottom Line") >= 0)

    # override recompute round-trip
    base = s.get("implied_share_price")
    rr = C.post(f"/api/valuation/{vid}/assumptions", json={"overrides": {"revenue_growth": 0.10}})
    if check(case, "override recompute 200", rr.status_code == 200, f"HTTP {rr.status_code}"):
        v2 = rr.json()
        g = next(a for a in v2["assumptions"] if a["key"] == "revenue_growth")
        check(case, "override provenance", g.get("source_type") == "USER_OVERRIDE"
              and abs((g.get("value") or 0) - 0.10) < 1e-9,
              f"source_type={g.get('source_type')} value={g.get('value')}")
        check(case, "recompute changed price",
              v2["summary"].get("implied_share_price") != base,
              f"{base} -> {v2['summary'].get('implied_share_price')}")
    rr = C.post(f"/api/valuation/{vid}/assumptions", json={"overrides": {"revenue_growth": 9.0}})
    check(case, "invalid override 422", rr.status_code == 422, f"HTTP {rr.status_code}")

    # scenario round-trip
    rr = C.post(f"/api/valuation/{vid}/scenarios", json={"active": "bear"})
    check(case, "scenario bear 200", rr.status_code == 200, f"HTTP {rr.status_code}")
    print(f"  -> vid={vid} price={base}", flush=True)


def excel_custom() -> None:
    """A different private company: overwrite every sample number with new values."""
    case = "excel:custom"
    print(f"\n=== {case} ===", flush=True)
    wb = load_workbook(io.BytesIO(_template()))

    # Services company: 3 years of revenue/EBIT/etc. (absolute dollars)
    income = {
        "Revenue": (8_000_000, 9_600_000, 11_520_000),
        "Cost of Goods Sold": (-4_400_000, -5_088_000, -5_990_400),
        "Gross Profit": (3_600_000, 4_512_000, 5_529_600),
        "Operating Expenses": (-2_320_000, -2_688_000, -3_100_800),
        "EBIT / Operating Profit": (1_280_000, 1_824_000, 2_428_800),
        "Interest Expense": (-96_000, -92_000, -88_000),
        "Income Before Tax (EBT)": (1_184_000, 1_732_000, 2_340_800),
        "Income Tax Expense": (-296_000, -433_000, -585_200),
        "Net Income": (888_000, 1_299_000, 1_755_600),
        "Depreciation & Amortization": (240_000, 268_000, 300_000),
    }
    cash = {
        "Operating Cash Flow": (1_450_000, 1_980_000, 2_560_000),
        "Depreciation & Amortization": (240_000, 268_000, 300_000),
        "Capital Expenditure": (-320_000, -350_000, -390_000),
        "Change in Net Working Capital": (-110_000, -130_000, -150_000),
    }
    balance = {
        "Cash & Cash Equivalents": (900_000, 1_100_000, 1_350_000),
        "Accounts Receivable": (780_000, 900_000, 1_050_000),
        "Inventory": (0, 0, 0),
        "Total Current Assets": (2_400_000, 2_750_000, 3_100_000),
        "Total Assets": (5_600_000, 6_300_000, 7_100_000),
        "Accounts Payable": (420_000, 470_000, 530_000),
        "Total Current Liabilities": (980_000, 1_060_000, 1_150_000),
        "Short-Term Debt": (0, 0, 0),
        "Long-Term Debt": (1_400_000, 1_250_000, 1_100_000),
        "Total Liabilities": (2_600_000, 2_500_000, 2_400_000),
        "Shareholders' Equity": (3_000_000, 3_800_000, 4_700_000),
        "Shares Outstanding": (4_000_000, 4_000_000, 4_000_000),
    }

    def overwrite(sheet: str, rows: dict) -> None:
        ws = wb[sheet]
        for row in ws.iter_rows(min_row=6, max_col=4):
            label = row[0].value
            if label in rows:
                for cell, val in zip(row[1:], rows[label]):
                    cell.value = val

    overwrite("Income Statement", income)
    overwrite("Cash Flow", cash)
    overwrite("Balance Sheet", balance)

    # Assumptions: blank beta so the model must use our explicit run override
    ws = wb["Assumptions"]
    for row in ws.iter_rows(min_row=5, max_col=2):
        if row[0].value == "Beta":
            row[1].value = None

    buf = io.BytesIO()
    wb.save(buf)
    r = _upload(buf.getvalue(), "Northwind Analytics")
    if not check(case, "upload 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    cid = r.json()["company_id"]

    r = _run(cid, overrides={"beta": 1.05, "share_price": 12.00},
             options={"capital_structure_method": "target", "run_comparables": False})
    if not check(case, "run 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    view = r.json()
    s = view["summary"]
    check(case, "status complete", s["status"] == "complete",
          f"status={s['status']} blocked={s.get('blocked_reasons')}")
    check(case, "implied price", (s.get("implied_share_price") or 0) > 0,
          f"price={s.get('implied_share_price')}")
    da = next((a for a in view["assumptions"] if a["key"] == "da_pct"), None)
    check(case, "da_pct present", da is not None and da["value"] is not None,
          f"value={None if da is None else da['value']}")
    check(case, "audit finalizable", view["audit"].get("can_finalize") is True,
          f"status={view['audit'].get('status')}")
    years = view.get("forecast", {}).get("years") or []
    check(case, "forecast >= 5y", len(years) >= 5, f"n={len(years)}")
    print(f"  -> vid={s['id']} price={s.get('implied_share_price')} "
          f"(user input 12.00)", flush=True)


def excel_no_da() -> None:
    """Edge case: no D&A anywhere + no D&A assumption -> da_pct must fall back,
    forecast must still run (the original 'missing drivers da_pct' failure)."""
    case = "excel:no_da"
    print(f"\n=== {case} ===", flush=True)
    wb = load_workbook(io.BytesIO(_template()))
    for sheet in ("Income Statement", "Cash Flow"):
        ws = wb[sheet]
        for row in ws.iter_rows(min_row=6, max_col=4):
            if row[0].value and "Depreciation" in str(row[0].value):
                for cell in row[1:]:
                    cell.value = None
    ws = wb["Assumptions"]
    for row in ws.iter_rows(min_row=5, max_col=2):
        if row[0].value == "D&A / Revenue":
            row[1].value = None

    buf = io.BytesIO()
    wb.save(buf)
    r = _upload(buf.getvalue(), "NoDA Services")
    if not check(case, "upload 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    cid = r.json()["company_id"]

    r = _run(cid, overrides={"beta": 1.0, "share_price": 8.00},
             options={"capital_structure_method": "target", "run_comparables": False})
    if not check(case, "run 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    view = r.json()
    s = view["summary"]
    check(case, "status complete", s["status"] == "complete",
          f"status={s['status']} blocked={s.get('blocked_reasons')}")
    da = next((a for a in view["assumptions"] if a["key"] == "da_pct"), None)
    check(case, "da_pct fallback value", da is not None and da["value"] is not None,
          f"value={None if da is None else da['value']}")
    if da:
        print(f"  da_pct: value={da['value']} status={da.get('status')} "
              f"source={da.get('source')}", flush=True)
    years = view.get("forecast", {}).get("years") or []
    check(case, "forecast >= 5y (was the reported crash)", len(years) >= 5,
          f"n={len(years)}")
    check(case, "implied price", (s.get("implied_share_price") or 0) > 0,
          f"price={s.get('implied_share_price')}")
    print(f"  -> vid={s['id']} price={s.get('implied_share_price')}", flush=True)


def excel_no_shares() -> None:
    """Missing shares: implied price must stay null, equity still computed."""
    case = "excel:no_shares"
    print(f"\n=== {case} ===", flush=True)
    wb = load_workbook(io.BytesIO(_template()))
    ws = wb["Balance Sheet"]
    for row in ws.iter_rows(min_row=6, max_col=4):
        if row[0].value == "Shares Outstanding":
            for cell in row[1:]:
                cell.value = None
    buf = io.BytesIO()
    wb.save(buf)
    r = _upload(buf.getvalue(), "NoShares Inc")
    if not check(case, "upload 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    cid = r.json()["company_id"]
    r = _run(cid, overrides={"beta": 1.0},
             options={"capital_structure_method": "target", "run_comparables": False})
    if not check(case, "run 200", r.status_code == 200, f"HTTP {r.status_code}"):
        dump_error(case, r)
        return
    s = r.json()["summary"]
    check(case, "price null (not fabricated)", s.get("implied_share_price") is None,
          f"price={s.get('implied_share_price')}")
    check(case, "equity still computed", (s.get("equity_value") or 0) > 0,
          f"equity={s.get('equity_value')}")


def excel_suite() -> None:
    for fn in (excel_default, excel_custom, excel_no_da, excel_no_shares):
        try:
            fn()
        except Exception:
            FAIL.append(f"{fn.__name__} exception")
            print(f"  EXCEPTION [{fn.__name__}]:", flush=True)
            traceback.print_exc()


# --------------------------------------------------------------------------

def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    try:
        h = C.get("/api/health")
        h.raise_for_status()
        print(f"health: {h.json()}", flush=True)
    except Exception as exc:
        print(f"BACKEND UNREACHABLE: {exc}", flush=True)
        return 2

    if which in ("public", "all"):
        public_suite()
    if which in ("excel", "all"):
        excel_suite()

    print(f"\n{'='*60}\nTOTAL: {len(PASS)} passed, {len(FAIL)} failed", flush=True)
    for f in FAIL:
        print(f"  FAILED: {f}", flush=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
