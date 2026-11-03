"""Forecasting stage — deterministic 5-year projection.

Every projected line carries the driver note that explains it. Optional
statistical/ML forecasting can be layered on later via `alternative` without
touching the authoritative deterministic model.
"""
from __future__ import annotations

from ..core.errors import MissingDataError
from ..schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from ..schemas.company import PeriodData
from ..schemas.valuation import ForecastResult, ForecastYear


def _sv(value: float, unit: Unit, note: str) -> SourcedValue:
    return SourcedValue(
        value=value, unit=unit, source_type=SourceType.MODEL_CALCULATION,
        source="Forecast engine", status=ValueStatus.CALCULATED, note=note,
    )


def build_forecast(
    periods: list[PeriodData],
    drivers: dict[str, float],
    *,
    years: int = 5,
    growth_overridden: bool = False,
) -> ForecastResult:
    """Revenue growth -> EBIT -> D&A, CapEx, NWC, EBITDA for `years` periods.

    drivers: revenue_growth, ebit_margin, da_pct, capex_pct, nwc_pct (decimals).
    Missing history for the base year raises — we never invent a starting point.
    """
    required = ("revenue_growth", "ebit_margin", "da_pct", "capex_pct", "nwc_pct")
    missing = [k for k in required if drivers.get(k) is None]
    if missing:
        raise MissingDataError(
            f"Forecast cannot run: missing drivers {', '.join(missing)}.",
            hint="Provide them on the Assumptions page (historical estimate or manual entry).",
        )
    if not periods or periods[-1].value("revenue") is None:
        raise MissingDataError(
            "Forecast cannot start: no base-year revenue in the historical data.",
            hint="Add revenue for the latest period on the Data Review page.",
        )

    base = periods[-1]
    base_revenue = base.value("revenue")
    base_da = base.value("da") if base.value("da") is not None else base.value("da_cf")
    base_ebit = base.value("ebit")

    g = drivers["revenue_growth"]
    ebit_margin = drivers["ebit_margin"]
    da_pct = drivers["da_pct"]
    capex_pct = drivers["capex_pct"]
    nwc_pct = drivers["nwc_pct"]

    last_da_margin = (base_da / base_revenue) if (base_da and base_revenue) else da_pct
    last_ebit_margin = (base_ebit / base_revenue) if (base_ebit is not None and base_revenue) else ebit_margin

    out: list[ForecastYear] = []
    prev_revenue = base_revenue
    base_year = base.fiscal_year

    for i in range(1, years + 1):
        fy = base_year + i
        period = f"FY{fy}"
        rev = prev_revenue * (1 + g)
        ebit = rev * ebit_margin
        # slight convergence toward the target margin if history disagrees
        if i == 1:
            note_margin = (f"EBIT = revenue x {ebit_margin:.2%} "
                           f"(historical latest margin {last_ebit_margin:.1%})")
        else:
            note_margin = f"EBIT = revenue x {ebit_margin:.2%}"
        da = rev * da_pct
        capex = rev * capex_pct
        delta_rev = rev - prev_revenue
        change_nwc = delta_rev * nwc_pct
        ebitda = ebit + da

        growth_note = (
            f"Revenue = {prev_revenue:,.0f} x (1 + {g:.2%})"
            + (" [USER OVERRIDE]" if i == 1 and growth_overridden else "")
        )
        out.append(ForecastYear(
            period=period, year_index=i,
            revenue_growth=_sv(g, Unit.PERCENT, growth_note),
            revenue=_sv(rev, Unit.CURRENCY, growth_note),
            ebit_margin=_sv(ebit_margin, Unit.PERCENT, note_margin),
            ebit=_sv(ebit, Unit.CURRENCY, note_margin),
            da=_sv(da, Unit.CURRENCY, f"D&A = revenue x {da_pct:.2%}"),
            capex=_sv(capex, Unit.CURRENCY, f"CapEx = revenue x {capex_pct:.2%}"),
            change_nwc=_sv(change_nwc, Unit.CURRENCY,
                           f"ΔNWC = Δrevenue x {nwc_pct:.2%} (working capital scales with growth)"),
            ebitda=_sv(ebitda, Unit.CURRENCY, "EBITDA = EBIT + D&A"),
            driver_note=f"Rev {g:.1%} | Margin {ebit_margin:.1%} | D&A {da_pct:.1%} | "
                        f"CapEx {capex_pct:.1%} | NWC {nwc_pct:.1%}",
        ))
        prev_revenue = rev

    return ForecastResult(
        method="deterministic_driver_model",
        years=out,
        start_period=out[0].period if out else "",
        assumptions_used=list(required),
        notes=[
            f"Revenue grows at a constant {g:.2%} — the single driver the user controls.",
            f"Margin held at {ebit_margin:.2%} vs latest historical {last_ebit_margin:.1%}.",
            "D&A and CapEx scale with revenue; incremental NWC scales with revenue growth.",
        ],
    )
