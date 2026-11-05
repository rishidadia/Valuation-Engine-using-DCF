"""Forecast note provenance: [USER OVERRIDE] only when growth is truly user-set.

The tag used to be appended unconditionally (its comparison key was never
populated), mislabelling model-derived growth as a user override in the
forecast, the report, and the audit trail.
"""
from datetime import date

import pytest

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


# ---------------- trajectories ----------------

from app.core.errors import ValidationError  # noqa: E402


def test_explicit_growth_path_is_applied_year_by_year():
    fc = build_forecast(_periods(), DRIVERS, years=3,
                        growth_path=[0.10, 0.08, 0.06])
    assert [round(y.revenue_growth.value, 4) for y in fc.years] == [0.10, 0.08, 0.06]
    base_rev = _periods()[-1].value("revenue")
    assert fc.years[0].revenue.value == pytest.approx(base_rev * 1.10)
    assert fc.years[1].revenue.value == pytest.approx(base_rev * 1.10 * 1.08)
    assert "explicit per-year path" in fc.notes[0]


def test_growth_fades_linearly_to_terminal_growth():
    fc = build_forecast(_periods(), DRIVERS, years=5, terminal_growth=0.03)
    growth = [round(y.revenue_growth.value, 6) for y in fc.years]
    # 0.05 -> 0.03 across 5 years, evenly
    assert growth == [0.05, 0.045, 0.04, 0.035, 0.03]
    assert "fades linearly" in fc.notes[0]


def test_margin_converges_from_history_then_holds():
    periods = _periods()  # latest margin = 0.20
    fc = build_forecast(periods, {**DRIVERS, "ebit_margin": 0.30},
                        years=4, margin_convergence_years=2)
    margins = [round(y.ebit_margin.value, 6) for y in fc.years]
    assert margins == [0.25, 0.30, 0.30, 0.30]
    assert "converges from the latest historical" in fc.notes[1]


def test_trajectory_longer_than_forecast_horizon_is_rejected():
    with pytest.raises(ValidationError):
        build_forecast(_periods(), DRIVERS, years=2, growth_path=[0.1, 0.1, 0.1])
