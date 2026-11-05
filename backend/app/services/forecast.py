"""Forecasting stage — deterministic 5-year projection.

Every projected line carries the driver note that explains it. Optional
statistical/ML forecasting can be layered on later via `alternative` without
touching the authoritative deterministic model.
"""
from __future__ import annotations

from ..core.errors import MissingDataError, ValidationError
from ..schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from ..schemas.company import PeriodData
from ..schemas.valuation import ForecastResult, ForecastYear


def _sv(value: float, unit: Unit, note: str) -> SourcedValue:
    return SourcedValue(
        value=value, unit=unit, source_type=SourceType.MODEL_CALCULATION,
        source="Forecast engine", status=ValueStatus.CALCULATED, note=note,
    )


def _validate_path(name: str, path: list[float] | None, years: int,
                   lo: float, hi: float) -> list[float] | None:
    """Validate an optional explicit per-year trajectory."""
    if not path:
        return None
    values = [float(v) for v in path]
    if len(values) > years:
        raise ValidationError(
            f"{name} has {len(values)} values but the forecast is {years} years long.",
            hint="Provide at most one value per forecast year; missing years fall back to the driver.",
        )
    for v in values:
        if not lo <= v <= hi:
            raise ValidationError(f"{name} value {v} outside plausible range [{lo}, {hi}].",
                                  hint="Rates are decimals: 0.08 for 8%.")
    return values


def build_forecast(
    periods: list[PeriodData],
    drivers: dict[str, float],
    *,
    years: int = 5,
    growth_overridden: bool = False,
    growth_path: list[float] | None = None,
    margin_path: list[float] | None = None,
    terminal_growth: float | None = None,
    margin_convergence_years: int = 0,
) -> ForecastResult:
    """Revenue growth -> EBIT -> D&A, CapEx, NWC, EBITDA for `years` periods.

    drivers: revenue_growth, ebit_margin, da_pct, capex_pct, nwc_pct (decimals).
    Missing history for the base year raises — we never invent a starting point.

    Trajectories (all optional, constant drivers remain the default):

    * ``growth_path`` / ``margin_path`` — explicit per-year decimals. Years not
      supplied fall back to the constant driver.
    * ``terminal_growth`` — linearly fades revenue growth from the driver in
      year 1 to this rate in the final year (growth convergence).
    * ``margin_convergence_years`` — fades the EBIT margin from the latest
      historical margin to the driver over that many years, then holds it.
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

    growth_values = _validate_path("growth_path", growth_path, years, -0.90, 2.00)
    margin_values = _validate_path("margin_path", margin_path, years, -1.00, 1.00)
    if margin_convergence_years < 0:
        raise ValidationError("margin_convergence_years cannot be negative")

    last_da_margin = (base_da / base_revenue) if (base_da and base_revenue) else da_pct
    last_ebit_margin = (base_ebit / base_revenue) if (base_ebit is not None and base_revenue) else ebit_margin

    out: list[ForecastYear] = []
    prev_revenue = base_revenue
    base_year = base.fiscal_year

    for i in range(1, years + 1):
        fy = base_year + i
        period = f"FY{fy}"

        # Revenue growth: explicit path > linear fade to terminal growth > constant.
        if growth_values is not None:
            g_i = growth_values[i - 1] if i <= len(growth_values) else g
        elif terminal_growth is not None and years > 1:
            g_i = g + (terminal_growth - g) * ((i - 1) / (years - 1))
        else:
            g_i = g

        # EBIT margin: explicit path > convergence from history > constant.
        if margin_values is not None:
            m_i = margin_values[i - 1] if i <= len(margin_values) else ebit_margin
        elif margin_convergence_years > 0:
            t = min(i, margin_convergence_years) / margin_convergence_years
            m_i = last_ebit_margin + (ebit_margin - last_ebit_margin) * t
        else:
            m_i = ebit_margin

        rev = prev_revenue * (1 + g_i)
        ebit = rev * m_i
        if i == 1:
            note_margin = (f"EBIT = revenue x {m_i:.2%} "
                           f"(historical latest margin {last_ebit_margin:.1%})")
        else:
            note_margin = f"EBIT = revenue x {m_i:.2%}"
        da = rev * da_pct
        capex = rev * capex_pct
        delta_rev = rev - prev_revenue
        change_nwc = delta_rev * nwc_pct
        ebitda = ebit + da

        growth_note = (
            f"Revenue = {prev_revenue:,.0f} x (1 + {g_i:.2%})"
            + (" [USER OVERRIDE]" if i == 1 and growth_overridden else "")
        )
        out.append(ForecastYear(
            period=period, year_index=i,
            revenue_growth=_sv(g_i, Unit.PERCENT, growth_note),
            revenue=_sv(rev, Unit.CURRENCY, growth_note),
            ebit_margin=_sv(m_i, Unit.PERCENT, note_margin),
            ebit=_sv(ebit, Unit.CURRENCY, note_margin),
            da=_sv(da, Unit.CURRENCY, f"D&A = revenue x {da_pct:.2%}"),
            capex=_sv(capex, Unit.CURRENCY, f"CapEx = revenue x {capex_pct:.2%}"),
            change_nwc=_sv(change_nwc, Unit.CURRENCY,
                           f"ΔNWC = Δrevenue x {nwc_pct:.2%} (working capital scales with growth)"),
            ebitda=_sv(ebitda, Unit.CURRENCY, "EBITDA = EBIT + D&A"),
            driver_note=f"Rev {g_i:.1%} | Margin {m_i:.1%} | D&A {da_pct:.1%} | "
                        f"CapEx {capex_pct:.1%} | NWC {nwc_pct:.1%}",
        ))
        prev_revenue = rev

    if growth_values is not None:
        growth_note = ("Revenue growth follows an explicit per-year path "
                       f"({growth_values[0]:.2%} to {growth_values[-1]:.2%}).")
    elif terminal_growth is not None and years > 1:
        growth_note = (f"Revenue growth fades linearly from {g:.2%} to terminal "
                       f"growth {terminal_growth:.2%} by {out[-1].period}.")
    else:
        growth_note = f"Revenue grows at a constant {g:.2%}."

    if margin_values is not None:
        margin_note = ("EBIT margin follows an explicit per-year path "
                       f"({margin_values[0]:.2%} to {margin_values[-1]:.2%}).")
    elif margin_convergence_years > 0:
        margin_note = (f"EBIT margin converges from the latest historical "
                       f"{last_ebit_margin:.2%} to {ebit_margin:.2%} over "
                       f"{margin_convergence_years} year(s), then holds.")
    else:
        margin_note = (f"Margin held at {ebit_margin:.2%} vs latest historical "
                       f"{last_ebit_margin:.1%}.")

    return ForecastResult(
        method="deterministic_driver_model",
        years=out,
        start_period=out[0].period if out else "",
        assumptions_used=list(required),
        notes=[
            growth_note,
            margin_note,
            "D&A and CapEx scale with revenue; incremental NWC scales with revenue growth.",
        ],
    )
