"""DCF: discounting, terminal value, enterprise/equity value, implied price.

Terminal value:
  Perpetuity growth : TV = FCF_n x (1 + g) / (WACC - g)     requires WACC > g
  Exit multiple     : TV = Terminal EBITDA x Exit Multiple
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.errors import TerminalValueError, ValidationError
from .capm import MAX_WACC, MIN_WACC


def discount_factors(wacc: float, n: int, convention: str = "end") -> list[float]:
    """Discount factor for each forecast year.

    convention: 'end' -> t = 1..n ; 'mid' -> t = 0.5..n-0.5
    """
    if n < 1:
        raise ValidationError("forecast years must be >= 1")
    if not MIN_WACC <= wacc <= MAX_WACC:
        raise ValidationError(f"WACC={wacc:.4f} outside plausible range")
    if convention not in ("end", "mid"):
        raise ValidationError(f"Unknown discounting convention: {convention}")
    offset = 0.0 if convention == "end" else 0.5
    return [1.0 / ((1.0 + wacc) ** (i + 1 - offset)) for i in range(n)]


def calculate_terminal_value_perpetuity(fcf_terminal_year: float, wacc: float, growth: float) -> float:
    """TV = FCF_n x (1+g) / (WACC - g)."""
    if growth is None:
        raise ValidationError("terminal growth rate is required for the perpetuity method")
    if growth >= wacc:
        raise TerminalValueError(
            f"Terminal growth ({growth:.2%}) must be strictly below WACC ({wacc:.2%}); "
            "the perpetuity terminal value is undefined (denominator <= 0).",
            hint="Lower the terminal growth rate or raise the discount rate. "
                 "Long-run growth cannot exceed the cost of capital indefinitely.",
        )
    if wacc <= 0:
        raise TerminalValueError(f"WACC={wacc:.4f} cannot discount cash flows")
    return fcf_terminal_year * (1.0 + growth) / (wacc - growth)


def calculate_terminal_value_exit_multiple(terminal_ebitda: float, exit_multiple: float) -> float:
    """TV = Terminal-year EBITDA x exit EV/EBITDA multiple."""
    if terminal_ebitda is None:
        raise ValidationError("terminal EBITDA is required for the exit multiple method")
    if exit_multiple is None or exit_multiple <= 0:
        raise ValidationError(
            f"exit_multiple={exit_multiple} must be positive",
            hint="Use e.g. 10.0 for 10x EV/EBITDA.",
        )
    return terminal_ebitda * exit_multiple


def pv_terminal_value(terminal_value: float, wacc: float, n: int, convention: str = "end") -> float:
    df = discount_factors(wacc, n, convention)[-1]
    return terminal_value * df


@dataclass
class DcfInputs:
    fcf: list[float]
    wacc: float
    cash: float | None = None
    debt: float | None = None
    shares_outstanding: float | None = None
    current_share_price: float | None = None
    terminal_growth: float | None = None
    terminal_ebitda: float | None = None
    exit_multiple: float | None = None
    convention: str = "end"
    terminal_fcf: float | None = None  # FCF_n x (1+g); defaults to last FCF


@dataclass
class DcfOutput:
    pv_fcfs: list[float]
    pv_forecast_total: float
    terminal_value: float | None
    pv_terminal_value: float | None
    enterprise_value: float | None
    equity_value: float | None
    implied_share_price: float | None
    upside_downside: float | None
    formula_lines: list[str] = field(default_factory=list)


def _enterprise_equity(
    pv_forecast_total: float, pv_tv: float | None,
    cash: float | None, debt: float | None,
) -> tuple[float | None, float | None]:
    ev = pv_forecast_total + (pv_tv or 0.0) if pv_tv is not None else None
    if ev is None:
        return None, None
    eq = ev + (cash or 0.0) - (debt or 0.0)
    return ev, eq


def calculate_enterprise_value(pv_forecast_fcf: float, pv_terminal_value: float | None) -> float:
    """EV = PV(Forecast FCF) + PV(Terminal Value)."""
    if pv_terminal_value is None:
        raise ValidationError("PV of terminal value is required for enterprise value")
    return pv_forecast_fcf + pv_terminal_value


def calculate_equity_value(enterprise_value: float, cash: float | None, debt: float | None) -> float:
    """Equity = EV + Cash - Debt."""
    if enterprise_value is None:
        raise ValidationError("enterprise value is required")
    return enterprise_value + (cash or 0.0) - (debt or 0.0)


def calculate_implied_share_price(equity_value: float, shares_outstanding: float | None) -> float:
    if not shares_outstanding or shares_outstanding <= 0:
        raise ValidationError(
            "shares_outstanding is required to compute an implied share price",
            hint="Add shares outstanding on the Data Review page (issued + outstanding, basic).",
        )
    return equity_value / shares_outstanding


def run_dcf(inputs: DcfInputs) -> DcfOutput:
    """Full discounting pass with the perpetuity-growth terminal method.

    Raises TerminalValueError when WACC <= terminal growth — the caller must
    surface the issue; no numbers are fabricated.
    """
    if not inputs.fcf:
        raise ValidationError("At least one forecast FCF is required")
    n = len(inputs.fcf)
    dfs = discount_factors(inputs.wacc, n, inputs.convention)
    pvs = [f * d for f, d in zip(inputs.fcf, dfs)]
    pv_total = sum(pvs)

    terminal_fcf = inputs.terminal_fcf if inputs.terminal_fcf is not None else inputs.fcf[-1]
    tv = calculate_terminal_value_perpetuity(terminal_fcf, inputs.wacc, inputs.terminal_growth or 0.0)
    pv_tv = pv_terminal_value(tv, inputs.wacc, n, inputs.convention)

    ev = calculate_enterprise_value(pv_total, pv_tv)
    eq = calculate_equity_value(ev, inputs.cash, inputs.debt)
    price = None
    upside = None
    try:
        price = calculate_implied_share_price(eq, inputs.shares_outstanding)
        if inputs.current_share_price:
            upside = price / inputs.current_share_price - 1.0
    except ValidationError:
        pass  # caller reports missing shares explicitly; we don't invent a price

    lines = [
        f"PV(FCF) over {n} years @ {inputs.wacc:.2%} = {pv_total:,.0f}",
        f"TV = FCF_{n} x (1 + g) / (WACC - g) = {tv:,.0f}",
        f"PV(TV) = TV x {dfs[-1]:.4f} = {pv_tv:,.0f}",
        f"EV = {pv_total:,.0f} + {pv_tv:,.0f} = {ev:,.0f}",
        f"Equity = EV + Cash - Debt = {ev:,.0f} + {inputs.cash or 0:,.0f} - {inputs.debt or 0:,.0f} = {eq:,.0f}",
    ]
    if price is not None:
        lines.append(f"Implied price = Equity / Shares = {eq:,.0f} / {inputs.shares_outstanding:,.0f} = {price:,.2f}")

    return DcfOutput(
        pv_fcfs=pvs, pv_forecast_total=pv_total, terminal_value=tv,
        pv_terminal_value=pv_tv, enterprise_value=ev, equity_value=eq,
        implied_share_price=price, upside_downside=upside, formula_lines=lines,
    )


def calculate_upside_downside(implied_price: float | None, current_price: float | None) -> float | None:
    if implied_price is None or not current_price:
        return None
    return implied_price / current_price - 1.0
