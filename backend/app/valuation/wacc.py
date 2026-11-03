"""Capital structure weights and WACC.

WACC = (E/(D+E)) x Re + (D/(D+E)) x Rd x (1 - T)
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import ValidationError
from .capm import MAX_TAX


@dataclass(frozen=True)
class Weights:
    equity_weight: float
    debt_weight: float
    market_value_equity: float
    market_value_debt: float
    formula: str

    def as_dict(self) -> dict:
        return {
            "equity_weight": self.equity_weight,
            "debt_weight": self.debt_weight,
            "market_value_equity": self.market_value_equity,
            "market_value_debt": self.market_value_debt,
            "formula": self.formula,
        }


def calculate_capital_weights(market_value_equity: float, market_value_debt: float) -> Weights:
    """E/(D+E) and D/(D+E) using market values."""
    if market_value_equity is None or market_value_debt is None:
        raise ValidationError("Both market value of equity and debt are required for weights")
    if market_value_equity < 0 or market_value_debt < 0:
        raise ValidationError(
            f"Capital structure values must be non-negative (E={market_value_equity}, D={market_value_debt})"
        )
    total = market_value_equity + market_value_debt
    if total <= 0:
        raise ValidationError(
            "Market value of equity + debt must be > 0 to compute weights",
            hint="Provide market capitalisation (price x shares) or a target capital structure.",
        )
    we, wd = market_value_equity / total, market_value_debt / total
    return Weights(
        equity_weight=we,
        debt_weight=wd,
        market_value_equity=market_value_equity,
        market_value_debt=market_value_debt,
        formula=f"E/(D+E) = {market_value_equity:,.0f}/{total:,.0f} = {we:.2%}; D/(D+E) = {wd:.2%}",
    )


def calculate_wacc(
    equity_weight: float,
    debt_weight: float,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float,
) -> float:
    """WACC = we*Re + wd*Rd*(1-T)."""
    if not 0 <= tax_rate <= MAX_TAX:
        raise ValidationError(f"tax_rate={tax_rate:.4f} outside [0%, {MAX_TAX:.0%}]")
    if abs((equity_weight + debt_weight) - 1.0) > 1e-6:
        raise ValidationError(
            f"equity_weight + debt_weight must sum to 1 (got {equity_weight + debt_weight:.6f})"
        )
    if equity_weight < 0 or debt_weight < 0:
        raise ValidationError("Capital weights cannot be negative")
    if cost_of_debt < 0:
        raise ValidationError("cost_of_debt cannot be negative")

    wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt * (1.0 - tax_rate)
    if wacc <= 0:
        raise ValidationError(
            f"Computed WACC is {wacc:.4%}, which is not usable as a discount rate",
            hint="Check cost of equity and cost of debt inputs.",
        )
    if wacc > 0.60:
        raise ValidationError(
            f"Computed WACC is {wacc:.2%}, outside the plausible range",
            hint="Check that rates are decimals (0.098 not 9.8).",
        )
    return wacc


def wacc_formula(equity_weight: float, cost_of_equity: float, debt_weight: float,
                 cost_of_debt: float, tax_rate: float) -> str:
    return (
        f"WACC = ({equity_weight:.2%} x {cost_of_equity:.2%}) + "
        f"({debt_weight:.2%} x {cost_of_debt:.2%} x (1 - {tax_rate:.2%})) "
        f"= {equity_weight * cost_of_equity:.4%} + {debt_weight * cost_of_debt * (1 - tax_rate):.4%}"
    )
