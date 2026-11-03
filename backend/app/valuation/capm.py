"""CAPM and cost-of-capital component calculations.

All functions are pure, LLM-free, and raise explicit errors on invalid input.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import ValidationError

# --- bounds used for sanity validation -----------------------------------
MIN_TAX, MAX_TAX = 0.0, 0.75
MIN_WACC, MAX_WACC = 0.005, 0.60
MIN_BETA, MAX_BETA = -1.0, 4.0


@dataclass(frozen=True)
class CapmResult:
    cost_of_equity: float
    risk_free_rate: float
    beta: float
    market_risk_premium: float
    formula: str

    def as_dict(self) -> dict:
        return {
            "cost_of_equity": self.cost_of_equity,
            "risk_free_rate": self.risk_free_rate,
            "beta": self.beta,
            "market_risk_premium": self.market_risk_premium,
            "formula": self.formula,
        }


def calculate_capm(risk_free_rate: float, beta: float, market_risk_premium: float) -> CapmResult:
    """CAPM: Re = Rf + Beta x MRP."""
    for name, v in (("risk_free_rate", risk_free_rate), ("market_risk_premium", market_risk_premium)):
        if v is None:
            raise ValidationError(f"{name} is required for CAPM")
        if not -0.05 <= v <= 0.30:
            raise ValidationError(
                f"{name}={v:.4f} outside the plausible range [-5%, 30%]",
                hint="Check whether a percentage (5.2) was passed where a decimal (0.052) is expected.",
            )
    if beta is None:
        raise ValidationError("beta is required for CAPM")
    if not MIN_BETA <= beta <= MAX_BETA:
        raise ValidationError(f"beta={beta:.3f} outside plausible range [{MIN_BETA}, {MAX_BETA}]")

    re = risk_free_rate + beta * market_risk_premium
    pct = lambda x: f"{x * 100:.2f}%"
    return CapmResult(
        cost_of_equity=re,
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        formula=f"Re = Rf + Beta x MRP = {pct(risk_free_rate)} + ({beta:.2f} x {pct(market_risk_premium)}) = {pct(re)}",
    )


def calculate_cost_of_debt(
    debt_instruments: list[tuple[float, float]] | None = None,
    manual_rate: float | None = None,
) -> float:
    """Cost of debt.

    - From instruments: weighted average of (amount, rate) pairs.
    - Manual: the supplied rate.

    Rates are decimals (0.055 == 5.5%).
    """
    if debt_instruments:
        total = sum(a for a, _ in debt_instruments)
        if total <= 0:
            raise ValidationError("Total debt instrument amount must be positive")
        for amt, rate in debt_instruments:
            if amt < 0:
                raise ValidationError(f"Debt instrument amount {amt} is negative")
            if not 0 <= rate <= 0.50:
                raise ValidationError(f"Debt instrument rate {rate:.4f} outside [0%, 50%]")
        return sum(a * r for a, r in debt_instruments) / total

    if manual_rate is None:
        raise ValidationError("cost_of_debt requires either debt_instruments or manual_rate")
    if not 0 <= manual_rate <= 0.50:
        raise ValidationError(
            f"cost_of_debt={manual_rate:.4f} outside [0%, 50%]",
            hint="Pass a decimal rate, e.g. 0.055 for 5.5%.",
        )
    return manual_rate


def calculate_after_tax_cost_of_debt(cost_of_debt: float, tax_rate: float) -> float:
    """Rd_after_tax = Rd x (1 - T)."""
    if not 0 <= tax_rate <= MAX_TAX:
        raise ValidationError(f"tax_rate={tax_rate:.4f} outside [0%, {MAX_TAX:.0%}]")
    if cost_of_debt < 0:
        raise ValidationError(f"cost_of_debt={cost_of_debt:.4f} cannot be negative")
    return cost_of_debt * (1.0 - tax_rate)
