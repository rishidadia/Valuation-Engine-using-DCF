"""Core compute — stage functions shared by agents, recompute, and scenarios.

    run_forecast -> run_wacc -> run_fcf -> run_dcf   (one deterministic chain)

`compute_core` composes them; sensitivity/scenarios call it with modified
values so every reported number comes from the same math.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas.company import PeriodData
from ..schemas.valuation import DcfResult, FcfSchedule, ForecastResult, WaccCalculation
from .dcf import build_dcf
from .fcf import build_fcf
from .forecast import build_forecast
from .wacc import build_wacc

DRIVER_KEYS = ("revenue_growth", "ebit_margin", "da_pct", "capex_pct", "nwc_pct")


@dataclass
class CoreResult:
    forecast: ForecastResult
    wacc: WaccCalculation
    fcf: FcfSchedule
    dcf: DcfResult

    @property
    def price(self) -> float | None:
        return self.dcf.implied_share_price

    @property
    def wacc_value(self) -> float | None:
        return self.wacc.wacc.value


def run_forecast(periods: list[PeriodData], values: dict[str, float | None],
                 options, *, growth_overridden: bool = False) -> ForecastResult:
    drivers = {k: values.get(k) for k in DRIVER_KEYS}
    return build_forecast(
        periods, drivers, years=options.forecast_years,
        growth_overridden=growth_overridden,
        growth_path=getattr(options, "growth_path", None),
        margin_path=getattr(options, "ebit_margin_path", None),
        terminal_growth=(values.get("terminal_growth")
                         if getattr(options, "growth_fade_to_terminal", False) else None),
        margin_convergence_years=getattr(options, "margin_convergence_years", 0),
    )


def run_wacc(periods: list[PeriodData], values: dict[str, float | None], options, *,
             debt_instruments: list[dict] | None = None,
             peers: list | None = None, private: bool = False) -> WaccCalculation:
    return build_wacc(values, options, periods, debt_instruments=debt_instruments,
                      peers=peers, private=private)


def run_fcf(forecast: ForecastResult, tax_rate: float, wacc: float, *,
            convention: str = "end") -> FcfSchedule:
    return build_fcf(forecast, tax_rate, wacc, convention=convention)


def run_dcf(fcf: FcfSchedule, *, wacc: float, values: dict[str, float | None],
            periods: list[PeriodData], options) -> DcfResult:
    return build_dcf(fcf, wacc=wacc, values=values, periods=periods, options=options)


def compute_core(
    periods: list[PeriodData],
    values: dict[str, float | None],
    options,
    *,
    debt_instruments: list[dict] | None = None,
    peers: list | None = None,
    private: bool = False,
    forced_wacc: float | None = None,
    growth_overridden: bool = False,
) -> CoreResult:
    """Forecast -> WACC -> FCF -> DCF.

    `forced_wacc` bypasses WACC *use* (sensitivity rows vary the discount rate
    directly); the WACC stage still runs so its validation applies.
    """
    forecast = run_forecast(periods, values, options, growth_overridden=growth_overridden)
    wacc_calc = run_wacc(periods, values, options,
                         debt_instruments=debt_instruments,
                         peers=peers, private=private)
    if forced_wacc is not None:
        wacc_value = forced_wacc
        wacc_calc.wacc.value = forced_wacc
        wacc_calc.wacc.note = "WACC forced for sensitivity analysis"
        wacc_calc.wacc.is_user_override = True
    else:
        wacc_value = wacc_calc.wacc.value

    tax = values.get("tax_rate")
    fcf = run_fcf(forecast, tax, wacc_value, convention=options.discount_convention)
    dcf = run_dcf(fcf, wacc=wacc_value, values=values, periods=periods, options=options)
    return CoreResult(forecast=forecast, wacc=wacc_calc, fcf=fcf, dcf=dcf)
