"""Forecast note provenance: [USER OVERRIDE] only when growth is truly user-set.

The tag used to be appended unconditionally (its comparison key was never
populated), mislabelling model-derived growth as a user override in the
forecast, the report, and the audit trail.
"""
from datetime import date

from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.schemas.company import PeriodData
from app.services.forecast import build_forecast

DRIVERS = {"revenue_growth": 0.05, "ebit_margin": 0.20, "da_pct": 0.05,
           "capex_pct": 0.04, "nwc_pct": 0.02}


def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.USER_INPUT, status=ValueStatus.USER_DATA)


def _periods() -> list[PeriodData]:
    out, rev = [], 100e6
    for i, y in enumerate(range(2024, 2026)):
        if i:
            rev *= 1.05
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 12, 31),
                              period_type="annual", currency="USD",
                              metrics={"revenue": _sv(rev), "ebit": _sv(rev * .2)}))
    return out


def test_model_growth_note_carries_no_override_tag():
    fc = build_forecast(_periods(), DRIVERS, years=3)
    assert "[USER OVERRIDE]" not in fc.years[0].revenue.note
    assert fc.years[0].revenue.note.startswith("Revenue = ")


def test_growth_note_tags_real_user_override():
    fc = build_forecast(_periods(), DRIVERS, years=3, growth_overridden=True)
    assert "[USER OVERRIDE]" in fc.years[0].revenue.note
    # only the base-year driver note is tagged — compounding years stay clean
    assert "[USER OVERRIDE]" not in fc.years[1].revenue.note
