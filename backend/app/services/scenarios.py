"""Scenario system — base / bull / bear / custom cases.

Each scenario re-runs the identical compute function with its own overrides,
so switching scenarios updates FCF, EV, equity and implied price consistently.
"""
from __future__ import annotations

from collections.abc import Callable

from ..core.errors import AppError
from ..schemas.valuation import ScenarioComparison, ScenarioResult

# Deltas applied to the base assumption values (percentage points for rates)
SCENARIO_TEMPLATES: dict[str, dict[str, float]] = {
    "base": {},
    "bull": {
        "revenue_growth": +0.030,
        "ebit_margin": +0.020,
        "terminal_growth": +0.005,
        "exit_multiple": +1.5,
    },
    "bear": {
        "revenue_growth": -0.035,
        "ebit_margin": -0.025,
        "terminal_growth": -0.005,
        "exit_multiple": -2.0,
    },
}

SCENARIO_LABELS = {
    "base": "Base Case",
    "bull": "Bull Case",
    "bear": "Bear Case",
    "custom": "Custom Case",
}

SCENARIO_DESCRIPTIONS = {
    "base": "Model estimates from history and market data, plus any user overrides.",
    "bull": "Growth +3.0pp, EBIT margin +2.0pp, terminal growth +0.5pp, exit multiple +1.5x.",
    "bear": "Growth −3.5pp, EBIT margin −2.5pp, terminal growth −0.5pp, exit multiple −2.0x.",
    "custom": "User-defined overrides.",
}

MIN_KEY, MAX_KEY = -1e9, 1e9


def apply_scenario(base_values: dict[str, float | None], name: str,
                   custom: dict[str, float] | None = None) -> dict[str, float]:
    """Absolute values for one scenario = base + template deltas (+ custom)."""
    values = {k: v for k, v in base_values.items() if v is not None}
    for key, delta in SCENARIO_TEMPLATES.get(name, {}).items():
        if key in values:
            values[key] = values[key] + delta
        elif key in ("exit_multiple", "terminal_growth"):
            values[key] = delta if key == "exit_multiple" else max(delta, 0.0)
    if name == "custom":
        values.update(custom or {})
    # keep scenarios inside the same plausibility bounds as overrides
    from .assumptions import BOUNDS
    for key in list(values):
        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            values[key] = min(max(values[key], lo), hi)
    return values


def evaluate_scenarios(
    compute: Callable[..., object],
    base_values: dict[str, float | None],
    *,
    active: str = "base",
    custom_overrides: dict[str, float] | None = None,
) -> ScenarioComparison:
    """compute(overrides, forced_wacc=None) -> CoreResult"""
    results: list[ScenarioResult] = []
    for name in ("base", "bull", "bear"):
        results.append(_one(compute, base_values, name, custom_overrides if name == "custom" else None))
    if active == "custom" or custom_overrides:
        results.append(_one(compute, base_values, "custom", custom_overrides or {}))

    return ScenarioComparison(active=active, scenarios=results)


def _one(compute, base_values, name: str, custom: dict[str, float] | None) -> ScenarioResult:
    overrides = apply_scenario(base_values, name, custom)
    try:
        core = compute({}, forced_wacc=None, scenario_values=overrides)
        dcf = core.dcf
        return ScenarioResult(
            name=name, label=SCENARIO_LABELS[name],
            overrides={k: v for k, v in overrides.items()
                       if base_values.get(k) != v},
            wacc=dcf.discount_rate,
            terminal_growth=dcf.terminal_growth,
            enterprise_value=dcf.enterprise_value,
            equity_value=dcf.equity_value,
            implied_share_price=dcf.implied_share_price,
            upside_downside=dcf.upside_downside,
            valid=dcf.valid, issue=dcf.issue,
        )
    except AppError as exc:
        return ScenarioResult(name=name, label=SCENARIO_LABELS[name],
                              valid=False, issue=exc.detail)
