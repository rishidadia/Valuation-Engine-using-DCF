"""FCF stage — unlevered free cash flow schedule with full components.

UFCF = EBIT x (1 - T) + D&A - CapEx - ΔNWC
"""
from __future__ import annotations

from ..schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from ..schemas.valuation import FcfSchedule, FcfYear, ForecastResult
from ..valuation import discount_factors, fcf_components


def _sv(value: float, unit: Unit, note: str) -> SourcedValue:
    return SourcedValue(value=value, unit=unit, source_type=SourceType.MODEL_CALCULATION,
                        source="FCF engine", status=ValueStatus.CALCULATED, note=note)


def build_fcf(
    forecast: ForecastResult,
    tax_rate: float,
    wacc: float,
    *,
    convention: str = "end",
) -> FcfSchedule:
    dfs = discount_factors(wacc, len(forecast.years), convention)
    years: list[FcfYear] = []
    margins: list[float] = []

    for y, df in zip(forecast.years, dfs):
        ebit = y.ebit.value
        da, capex, nwc = y.da.value, y.capex.value, y.change_nwc.value
        c = fcf_components(ebit, tax_rate, da, capex, nwc)
        pv = c.fcf * df
        years.append(FcfYear(
            period=y.period, year_index=y.year_index,
            revenue=y.revenue,
            ebit=_sv(c.ebit, Unit.CURRENCY, y.ebit.note or ""),
            tax_rate=_sv(tax_rate, Unit.PERCENT, "Applied to EBIT (unlevered)"),
            tax_expense=_sv(c.tax_expense, Unit.CURRENCY, "Tax = EBIT x tax rate"),
            nopat=_sv(c.nopat, Unit.CURRENCY, "NOPAT = EBIT x (1 - T)"),
            da=_sv(c.da, Unit.CURRENCY, "From forecast"),
            capex=_sv(c.capex, Unit.CURRENCY, "From forecast (positive = outflow)"),
            change_nwc=_sv(c.change_nwc, Unit.CURRENCY, "From forecast (positive = outflow)"),
            fcf=_sv(c.fcf, Unit.CURRENCY, c.formula),
            discount_factor=round(df, 6),
            pv_fcf=round(pv, 2),
            formula=c.formula,
        ))
        if y.revenue.value:
            margins.append(c.fcf / y.revenue.value)

    cagr = None
    if len(years) >= 2:
        first, last = years[0].fcf.value, years[-1].fcf.value
        if first and first > 0 and last and last > 0:
            cagr = (last / first) ** (1 / (len(years) - 1)) - 1

    return FcfSchedule(
        years=years,
        fcf_cagr=cagr,
        margins=margins,
        notes=[
            f"Tax charged on EBIT (unlevered view): {tax_rate:.2%}.",
            "Expand any year to see EBIT → tax → NOPAT → +D&A → −CapEx → −ΔNWC.",
            f"Discount factors use {convention}-year convention at WACC {wacc:.2%}.",
        ],
    )
