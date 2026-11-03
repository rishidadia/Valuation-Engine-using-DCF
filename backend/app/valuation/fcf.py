"""Unlevered free cash flow calculations.

UFCF = EBIT x (1 - Tax Rate) + D&A - CapEx - Change in NWC
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import ValidationError
from .capm import MAX_TAX


def calculate_nopat(ebit: float, tax_rate: float) -> float:
    """NOPAT = EBIT x (1 - T)."""
    if tax_rate is None or not 0 <= tax_rate <= MAX_TAX:
        raise ValidationError(f"tax_rate={tax_rate} outside [0%, {MAX_TAX:.0%}]")
    return ebit * (1.0 - tax_rate)


def calculate_fcf(
    ebit: float,
    tax_rate: float,
    da: float,
    capex: float,
    change_nwc: float,
) -> float:
    """Unlevered free cash flow for one period.

    capex and change_nwc are signed as cash outflows (positive numbers mean
    cash outflow, matching how analysts state 'CapEx of $50M').
    """
    for name, v in (("ebit", ebit), ("da", da), ("capex", capex), ("change_nwc", change_nwc)):
        if v is None:
            raise ValidationError(f"{name} is required to compute FCF")
    nopat = calculate_nopat(ebit, tax_rate)
    return nopat + da - capex - change_nwc


@dataclass(frozen=True)
class FcfComponents:
    ebit: float
    tax_rate: float
    tax_expense: float
    nopat: float
    da: float
    capex: float
    change_nwc: float
    fcf: float
    formula: str


def fcf_components(
    ebit: float, tax_rate: float, da: float, capex: float, change_nwc: float
) -> FcfComponents:
    """Same as calculate_fcf but returns every intermediate for display."""
    nopat = calculate_nopat(ebit, tax_rate)
    tax_expense = ebit * tax_rate
    fcf = nopat + da - capex - change_nwc
    formula = (
        f"FCF = EBIT x (1 - T) + D&A - CapEx - dNWC "
        f"= ({ebit:,.0f} x (1 - {tax_rate:.2%})) + {da:,.0f} - {capex:,.0f} - {change_nwc:,.0f} "
        f"= {fcf:,.0f}"
    )
    return FcfComponents(
        ebit=ebit, tax_rate=tax_rate, tax_expense=tax_expense, nopat=nopat,
        da=da, capex=capex, change_nwc=change_nwc, fcf=fcf, formula=formula,
    )


def fcf_margin(fcf: float, revenue: float) -> float | None:
    if not revenue:
        return None
    return fcf / revenue
