"""DCF-labs financial calculation engine.

Every function here is pure Python — no LLM involvement, fully unit tested.
"""
from .beta import (
    aggregate_beta,
    comparable_beta_estimate,
    calculate_relevered_beta,
    calculate_unlevered_beta,
    regression_beta,
)
from .capm import (
    CapmResult,
    calculate_after_tax_cost_of_debt,
    calculate_capm,
    calculate_cost_of_debt,
)
from .dcf import (
    DcfInputs,
    DcfOutput,
    calculate_enterprise_value,
    calculate_equity_value,
    calculate_implied_share_price,
    calculate_terminal_value_exit_multiple,
    calculate_terminal_value_perpetuity,
    calculate_upside_downside,
    discount_factors,
    pv_terminal_value,
    run_dcf,
)
from .fcf import calculate_fcf, calculate_nopat, fcf_components, fcf_margin
from .sensitivity import (
    SensitivityGrid,
    calculate_sensitivity_matrix,
    make_grid,
    summarize_range,
    tornado_swing,
)
from .wacc import Weights, calculate_capital_weights, calculate_wacc, wacc_formula

__all__ = [
    "calculate_capm", "CapmResult", "calculate_cost_of_debt",
    "calculate_after_tax_cost_of_debt", "calculate_capital_weights", "Weights",
    "calculate_wacc", "wacc_formula", "calculate_nopat", "calculate_fcf",
    "fcf_components", "fcf_margin", "calculate_terminal_value_perpetuity",
    "calculate_terminal_value_exit_multiple", "calculate_enterprise_value",
    "calculate_equity_value", "calculate_implied_share_price", "run_dcf",
    "discount_factors", "pv_terminal_value", "calculate_upside_downside",
    "calculate_unlevered_beta", "calculate_relevered_beta", "regression_beta",
    "aggregate_beta", "comparable_beta_estimate",
    "calculate_sensitivity_matrix", "SensitivityGrid", "make_grid",
    "summarize_range", "tornado_swing",
]
