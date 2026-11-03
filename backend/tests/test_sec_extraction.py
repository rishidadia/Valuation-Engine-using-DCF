"""SEC extraction regression tests.

1. Concept union across years: a filer may switch tags between filings — the
   first matching concept must not cut off years reported under a later one
   (Alphabet: FY2025 under `Revenues`, earlier years under the customer-contract
   concept — FY2025 revenue used to be dropped entirely, breaking the forecast
   and peer multiples for GOOGL).
2. Shares fallback: Alphabet never tags dei:EntityCommonStockSharesOutstanding —
   without a fallback, market cap, EV/EBITDA multiples, and implied share price
   are impossible for such filers.
"""
from app.data.providers.sec import SecEdgarProvider


def _fact(year: int, val: float, *, start: str | None = None, end_yr: int | None = None) -> dict:
    y = end_yr or year
    return {
        "cik": 100, "accn": "0000100-25-000009", "form": "10-K",
        "filed": f"{y + 1}-01-30",
        "start": start if start else f"{year}-01-01",
        "end": f"{y}-12-31", "val": val,
    }


def _concept(*pairs: tuple[int, float]) -> dict:
    return {"units": {"USD": [_fact(y, v) for y, v in pairs]}}


def test_revenue_union_across_concepts():
    """FY2024 exists under both tags (first wins); FY2025 only under `Revenues`."""
    facts = {
        "facts": {
            "us-gaap": {
                # higher-priority concept stops after FY2024
                "RevenueFromContractWithCustomerExcludingAssessedTax":
                    _concept((2023, 300.0), (2024, 350.0)),
                # filer switched tags: present for FY2024 (identical) and FY2025
                "Revenues": _concept((2024, 350.0), (2025, 400.0)),
                "OperatingIncomeLoss": _concept((2023, 60.0), (2024, 70.0), (2025, 90.0)),
                "NetIncomeLoss": _concept((2023, 45.0), (2024, 52.0), (2025, 68.0)),
                "Depreciation": _concept((2023, 15.0), (2024, 17.0), (2025, 21.0)),
            }
        }
    }
    periods, warnings, prov = SecEdgarProvider().extract_periods(facts, "USD")
    by_fy = {p.fiscal_year: p for p in periods}

    assert by_fy[2023].value("revenue") == 300.0
    # overlapping year keeps the higher-priority concept's value
    assert by_fy[2024].value("revenue") == 350.0
    prov_2024 = next(p for p in prov if p["key"] == "revenue" and p["year"] == 2024)
    assert prov_2024["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    # the year reported only under the later tag is no longer dropped
    assert by_fy[2025].value("revenue") == 400.0
    prov_2025 = next(p for p in prov if p["key"] == "revenue" and p["year"] == 2025)
    assert prov_2025["concept"] == "Revenues"
    assert warnings == []


def test_shares_fallback_when_dei_absent():
    """No dei tag → us-gaap:CommonStockSharesOutstanding (labelled) is used."""
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": _concept((2025, 500.0)),
                "OperatingIncomeLoss": _concept((2025, 100.0)),
                "CommonStockSharesOutstanding": {"units": {"shares": [
                    {**_fact(2024, 900e6, start=None), "start": None},
                    {**_fact(2025, 950e6, start=None), "start": None},
                ]}},
            }
            # note: no "dei" namespace at all
        }
    }
    periods, _, prov = SecEdgarProvider().extract_periods(facts, "USD")
    p = periods[-1]
    shares = p.value("shares_outstanding")
    assert shares == 950e6
    sv = p.metrics["shares_outstanding"]
    assert sv.source == "SEC EDGAR XBRL CommonStockSharesOutstanding"
    assert "dei tag absent" in (sv.note or "")
    assert {"key": "shares_outstanding", "year": 2025,
            "concept": "CommonStockSharesOutstanding"} in prov


def test_dei_shares_still_take_priority():
    """When dei exists its value is used unchanged (AAPL/MSFT behavior)."""
    facts = {
        "facts": {
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
                {"cik": 100, "accn": "0000100-25-000009", "form": "10-K",
                 "filed": "2025-01-30", "end": "2025-01-15", "val": 1_000_000.0},
            ]}}},
            "us-gaap": {
                "Revenues": _concept((2025, 500.0)),
                "CommonStockSharesOutstanding": {"units": {"shares": [
                    {**_fact(2025, 950e6), "start": None},
                ]}},
            },
        }
    }
    periods, _, _ = SecEdgarProvider().extract_periods(facts, "USD")
    p = periods[-1]
    assert p.value("shares_outstanding") == 1_000_000.0
    assert p.metrics["shares_outstanding"].source.startswith("SEC EDGAR dei:")
