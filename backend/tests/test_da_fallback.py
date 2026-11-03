"""D&A derivation regression tests.

MSFT and GOOGL never tag a combined us-gaap D&A concept — they report
Depreciation and AmortizationOfIntangibleAssets separately (MSFT uses a company
extension tag that companyfacts does not expose). Without the component-sum
fallback, `da` stays missing, da_pct stays None, and the forecast refuses to
run with "missing drivers da_pct".
"""
from datetime import date

from app.data.providers.sec import SecEdgarProvider
from app.schemas.company import CompanyInfo, PeriodData
from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.services.forecast import build_forecast
from app.services.historical import analyze

DRIVERS = ("revenue_growth", "ebit_margin", "da_pct", "capex_pct", "nwc_pct")


def _fact(year: int, val: float, *, cik: int = 100, accn: str = "0000100-25-000009") -> dict:
    return {
        "cik": cik, "accn": accn, "form": "10-K", "filed": f"{year + 1}-01-30",
        "start": f"{year}-01-01", "end": f"{year}-12-31", "val": val,
    }


def _concept(*pairs: tuple[int, float]) -> dict:
    return {"units": {"USD": [_fact(y, v) for y, v in pairs]}}


def test_sec_sums_da_components_when_combined_concept_absent():
    """MSFT-style filing: no combined D&A concept — components must be summed."""
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": _concept((2024, 200_000.0), (2025, 220_000.0)),
                "OperatingIncomeLoss": _concept((2024, 40_000.0), (2025, 46_000.0)),
                "NetIncomeLoss": _concept((2024, 30_000.0), (2025, 34_000.0)),
                "Depreciation": _concept((2024, 6_000.0), (2025, 7_000.0)),
                "AmortizationOfIntangibleAssets": _concept((2024, 2_000.0), (2025, 3_000.0)),
                # NOTE: deliberately no DepreciationDepletionAndAmortization / etc.
            }
        }
    }
    periods, warnings, prov = SecEdgarProvider().extract_periods(facts, "USD")
    assert periods, "extract_periods must still return periods"

    p25 = next(p for p in periods if p.fiscal_year == 2025)
    da = p25.metrics["da"]
    assert da.value == 10_000.0  # 7,000 + 3,000
    assert da.source_type == SourceType.PUBLIC_API
    assert "Depreciation + AmortizationOfIntangibleAssets (sum)" in da.source
    # provenance records the exact concepts used
    assert {"key": "da", "year": 2025,
            "concept": "Depreciation + AmortizationOfIntangibleAssets"} in prov
    # EBITDA becomes derivable too (EBIT + D&A)
    assert p25.value("ebitda") == 56_000.0
    assert warnings == []


def test_sec_prefers_combined_concept_over_components():
    """AAPL-style filing: the combined concept wins; no component sum needed."""
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": _concept((2025, 100_000.0)),
                "OperatingIncomeLoss": _concept((2025, 25_000.0)),
                "DepreciationDepletionAndAmortization": _concept((2025, 9_000.0)),
                "Depreciation": _concept((2025, 8_000.0)),
            }
        }
    }
    periods, _, _ = SecEdgarProvider().extract_periods(facts, "USD")
    p25 = periods[0]
    assert p25.value("da") == 9_000.0
    assert "(sum)" not in p25.metrics["da"].source


def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.USER_INPUT, status=ValueStatus.USER_DATA)


def _periods_without_da(years: int = 4) -> list[PeriodData]:
    out, rev = [], 100e6
    for i, y in enumerate(range(2022, 2022 + years)):
        if i:
            rev *= 1.08
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 12, 31),
                              period_type="annual", currency="USD", metrics={
            "revenue": _sv(rev), "cogs": _sv(rev * .6), "gross_profit": _sv(rev * .4),
            "ebit": _sv(rev * .18), "ebt": _sv(rev * .17), "income_tax_expense": _sv(rev * .04),
            "net_income": _sv(rev * .13), "capex": _sv(rev * .04),
            "cash": _sv(50e6), "total_debt": _sv(120e6),
            "shares_outstanding": _sv(10e6, Unit.COUNT),
            "accounts_receivable": _sv(rev * .12), "inventory": _sv(rev * .10),
            "accounts_payable": _sv(rev * .08),
        }))
    return out


def test_da_pct_always_produces_runnable_drivers():
    """da_pct must never stay None — forecast must run with explicit provenance."""
    periods = _periods_without_da()
    analysis = analyze(periods)
    proposed = {a.key: a for a in analysis.proposed_assumptions}

    da = proposed["da_pct"]
    assert da.value is not None
    assert abs(da.value - 0.04) < 1e-9  # steady-state proxy: D&A ≈ CapEx intensity
    assert "NOT DERIVABLE" in da.note
    assert da.historical_value is None  # still honest: no historical D&A exists

    drivers = {k: proposed[k].value for k in DRIVERS}
    assert all(v is not None for v in drivers.values())
    fc = build_forecast(periods, drivers, years=5)
    assert len(fc.years) == 5
    assert fc.assumptions_used == list(DRIVERS)
