"""Agent 6 — WACC Agent.

CAPM, capital weights, cost of debt, comparable-beta unlevering/relevering —
all executed by pure Python functions; the agent only orchestrates and reports.
"""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_wacc
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "wacc", "WACC Agent",
                   "Compute CAPM, weights, cost of debt, WACC (transparent formulas)") as run:
        stage_wacc(ctx)
        w = ctx.wacc
        run.result = (
            f"WACC {w.wacc.value:.2%} = {w.equity_weight.value:.0%} x {w.cost_of_equity.value:.2%} "
            f"+ {w.debt_weight.value:.0%} x {w.cost_of_debt.value:.2%} x (1 − {w.tax_rate.value:.0%})"
        )
        run.warnings = list(w.warnings)
        if w.beta_details:
            comp = [d for d in w.beta_details if d.unlevered_beta is not None]
            if comp:
                run.result += f"; beta via {len(comp)} comparable(s)" if w.beta_method == "comparables" \
                    else f"; beta {w.beta.value:.2f} ({w.beta_method})"
        if w.debt_instruments:
            run.result += f"; {len(w.debt_instruments)} debt instrument(s) weighted"
