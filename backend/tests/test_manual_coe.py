"""Manual cost of equity must not require beta.

WACC only needs beta through CAPM. When the user supplies an expected return
directly, demanding beta (and computing a CAPM reference from it) added a
spurious data requirement that blocked otherwise complete valuations.
"""
from datetime import date

import pytest

from app.core.errors import MissingDataError
from app.schemas.company import PeriodData
from app.schemas.valuation import ValuationOptions
from app.services.wacc import build_wacc


def _periods() -> list[PeriodData]:
    return [PeriodData(period="FY2025", fiscal_year=2025, end_date=date(2025, 12, 31))]


def _values(**over) -> dict[str, float | None]:
    values: dict[str, float | None] = {
        "tax_rate": 0.21,
        "cost_of_equity": 0.12,
        "cost_of_debt": 0.06,
        "target_de": 0.25,
        "market_equity": 1e9,
        "market_debt": 2.5e8,
        "terminal_growth": 0.025,
    }
    values.update(over)
    return values


def _options() -> ValuationOptions:
    return ValuationOptions(cost_of_equity_method="manual",
                            capital_structure_method="target")


def test_manual_cost_of_equity_works_without_beta_or_risk_free():
    out = build_wacc(_values(), _options(), _periods())

    assert out.cost_of_equity.value == pytest.approx(0.12)
    assert out.beta.value is None
    assert out.wacc.value == pytest.approx(0.8 * 0.12 + 0.2 * 0.06 * 0.79)
    assert "not computed" in out.capm_formula
    assert any("manual cost of equity is in use" in w for w in out.warnings)


def test_manual_cost_of_equity_still_shows_capm_reference_when_beta_available():
    values = _values(beta=1.1, risk_free_rate=0.04, market_risk_premium=0.05)
    out = build_wacc(values, _options(), _periods())

    assert out.cost_of_equity.value == pytest.approx(0.12)
    assert out.beta.value == pytest.approx(1.1)
    assert "CAPM reference" in out.capm_formula


def test_capm_still_requires_beta():
    values = _values()  # no beta key
    with pytest.raises(MissingDataError) as ei:
        build_wacc(values, ValuationOptions(capital_structure_method="target"), _periods())
    assert "Beta" in str(ei.value.detail)
