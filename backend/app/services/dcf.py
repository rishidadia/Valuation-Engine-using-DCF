"""DCF stage — discounting, terminal value (both methods), equity bridge.

If WACC <= terminal growth the perpetuity method is marked invalid with an
explicit issue string; the valuation is not silently completed.
"""
from __future__ import annotations

from ..core.errors import TerminalValueError, ValidationError
from ..schemas.common import SourceType, Unit
from ..schemas.company import PeriodData
from ..schemas.valuation import DcfResult, FcfSchedule, TerminalMethodResult
from ..valuation import (
    calculate_equity_value,
    calculate_implied_share_price,
    calculate_terminal_value_exit_multiple,
    calculate_terminal_value_perpetuity,
    calculate_upside_downside,
)


def _fmt(x: float | None) -> str:
    return f"{x:,.0f}" if x is not None else "n/a"


def build_dcf(
    fcf: FcfSchedule,
    *,
    wacc: float,
    values: dict[str, float | None],
    periods: list[PeriodData],
    options,
) -> DcfResult:
    warnings: list[str] = []
    years = fcf.years
    if not years:
        return DcfResult(discount_rate=wacc, forecast_years=0, valid=False,
                         issue="No forecast cash flows to discount.")

    dfs = [y.discount_factor for y in years]
    pvs = [y.pv_fcf or 0.0 for y in years]
    pv_total = sum(pvs)
    n = len(years)

    terminal_growth = values.get("terminal_growth")
    exit_multiple = values.get("exit_multiple")
    terminal_fcf = years[-1].fcf.value or 0.0
    terminal_ebitda = ((years[-1].ebit.value or 0.0) + (years[-1].da.value or 0.0)) \
        if (years[-1].ebit.value is not None and years[-1].da.value is not None) else None

    cash = _latest(periods, "cash")
    debt = _latest(periods, "total_debt")
    shares = values.get("shares_outstanding")
    current_price = values.get("share_price")

    pv_rows = [
        {"period": y.period, "fcf": y.fcf.value, "discount_factor": y.discount_factor,
         "pv": y.pv_fcf, "index": y.year_index}
        for y in years
    ]

    methods: list[TerminalMethodResult] = []

    # ---- perpetuity growth ---------------------------------------------------
    try:
        tv = calculate_terminal_value_perpetuity(terminal_fcf, wacc, terminal_growth)
        pv_tv = tv * (dfs[-1] or 0.0)
        ev = pv_total + pv_tv
        eq = calculate_equity_value(ev, cash, debt)
        price = None
        upside = None
        try:
            price = calculate_implied_share_price(eq, shares)
            upside = calculate_upside_downside(price, current_price)
        except ValidationError as exc:
            warnings.append(exc.detail)
        methods.append(TerminalMethodResult(
            method="perpetuity_growth", label="Perpetuity Growth (Gordon)",
            terminal_value=tv, pv_terminal_value=pv_tv, ev=ev, equity_value=eq,
            implied_share_price=price,
            formula=(f"TV = FCF_{n} x (1 + g) / (WACC - g) = "
                     f"{_fmt(terminal_fcf)} x (1 + {(terminal_growth or 0):.2%}) / "
                     f"({wacc:.2%} - {(terminal_growth or 0):.2%}) = {_fmt(tv)}"),
            inputs={"terminal_fcf": terminal_fcf, "wacc": wacc,
                    "terminal_growth": terminal_growth or 0.0, "pv_factor": dfs[-1] or 0.0},
            valid=True,
        ))
    except TerminalValueError as exc:
        methods.append(TerminalMethodResult(
            method="perpetuity_growth", label="Perpetuity Growth (Gordon)",
            valid=False, issue=exc.detail,
            formula="TV = FCF_n x (1 + g) / (WACC - g) — undefined when WACC <= g",
            inputs={"wacc": wacc, "terminal_growth": terminal_growth or 0.0},
        ))
        warnings.append(exc.detail)

    # ---- exit multiple --------------------------------------------------------
    if terminal_ebitda and exit_multiple:
        try:
            tv2 = calculate_terminal_value_exit_multiple(terminal_ebitda, exit_multiple)
            pv_tv2 = tv2 * (dfs[-1] or 0.0)
            ev2 = pv_total + pv_tv2
            eq2 = calculate_equity_value(ev2, cash, debt)
            price2 = upside2 = None
            try:
                price2 = calculate_implied_share_price(eq2, shares)
                upside2 = calculate_upside_downside(price2, current_price)
            except ValidationError:
                pass
            methods.append(TerminalMethodResult(
                method="exit_multiple", label="Exit Multiple (EV/EBITDA)",
                terminal_value=tv2, pv_terminal_value=pv_tv2, ev=ev2, equity_value=eq2,
                implied_share_price=price2,
                formula=(f"TV = terminal EBITDA x exit multiple = "
                         f"{_fmt(terminal_ebitda)} x {exit_multiple:.2f}x = {_fmt(tv2)}"),
                inputs={"terminal_ebitda": terminal_ebitda, "exit_multiple": exit_multiple,
                        "pv_factor": dfs[-1] or 0.0},
                valid=True,
            ))
        except ValidationError as exc:
            methods.append(TerminalMethodResult(
                method="exit_multiple", label="Exit Multiple (EV/EBITDA)",
                valid=False, issue=exc.detail,
            ))
            warnings.append(exc.detail)
    else:
        methods.append(TerminalMethodResult(
            method="exit_multiple", label="Exit Multiple (EV/EBITDA)",
            valid=False,
            issue=("Terminal EBITDA or exit multiple unavailable — exit-multiple method not computable."
                   if not terminal_ebitda else "No exit multiple set."),
        ))

    selected_name = options.terminal_method
    selected = next((m for m in methods if m.method == selected_name and m.valid), None)
    fallback = next((m for m in methods if m.valid), None)
    if selected is None and fallback is not None:
        selected = fallback
        warnings.append(
            f"Requested terminal method '{selected_name}' is unavailable; "
            f"using '{fallback.method}' instead."
        )

    valid = selected is not None
    issue = None
    if not valid:
        issue = next((m.issue for m in methods if m.issue), "No terminal value method could be computed.")

    result = DcfResult(
        discount_rate=wacc,
        forecast_years=n,
        pv_rows=pv_rows,
        pv_forecast_fcf=pv_total,
        terminal_methods=methods,
        selected_method=(selected.method if selected else options.terminal_method),
        terminal_growth=terminal_growth,
        exit_multiple=exit_multiple,
        cash=cash,
        debt=debt,
        shares_outstanding=shares,
        current_share_price=current_price,
        fcf_cagr=fcf.fcf_cagr,
        valid=valid,
        issue=issue,
        warnings=warnings,
    )
    if selected and selected.valid:
        result.enterprise_value = selected.ev
        result.equity_value = selected.equity_value
        result.implied_share_price = selected.implied_share_price
        result.upside_downside = calculate_upside_downside(selected.implied_share_price, current_price)
        result.bridge = [
            {"label": "PV of forecast FCF (5y)", "value": pv_total,
             "detail": f"Σ FCF_t x DF_t @ {wacc:.2%}"},
            {"label": f"PV of terminal value ({selected.label})",
             "value": selected.pv_terminal_value, "detail": selected.formula},
            {"label": "Enterprise Value", "value": selected.ev,
             "detail": "PV(FCF) + PV(TV)"},
            {"label": "+ Cash", "value": cash or 0.0, "detail": "Latest balance sheet"},
            {"label": "− Total Debt", "value": -(debt or 0.0),
             "detail": "Latest balance sheet (short + long term)"},
            {"label": "Equity Value", "value": selected.equity_value,
             "detail": "EV + Cash − Debt"},
            {"label": "÷ Shares Outstanding", "value": shares,
             "detail": "For implied share price"},
            {"label": "Implied Share Price", "value": selected.implied_share_price,
             "detail": (f"vs current {current_price:,.2f} ({result.upside_downside:+.1%})"
                        if current_price and result.upside_downside is not None
                        else "no market price (private)")},
        ]
    return result


def _latest(periods: list[PeriodData], key: str) -> float | None:
    for p in reversed(periods):
        v = p.value(key)
        if v is not None:
            return v
    return None
