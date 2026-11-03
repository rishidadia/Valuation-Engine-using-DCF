"""Agent 5 — Forecasting Agent.

Builds the deterministic multi-year forecast from approved drivers.
(Optional statistical/ML forecasting can be added as a comparison payload;
the deterministic model remains authoritative unless the user selects another.)
"""
from __future__ import annotations

from ..services.engine import (
    PipelineContext, stage_assumptions, stage_forecast,
)
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "forecast", "Forecasting Agent",
                   "Build driver-based forecast: revenue, margins, D&A, CapEx, NWC") as run:
        if not ctx.assumptions:
            stage_assumptions(ctx)
        overrides = [a.key for a in ctx.assumptions if a.is_override]
        stage_forecast(ctx)
        f = ctx.forecast
        run.result = (
            f"{len(f.years)}-year forecast ({f.start_period} → {f.years[-1].period}) "
            f"using {', '.join(f.assumptions_used)}"
        )
        if overrides:
            run.result += f"; overrides applied: {', '.join(overrides)}"
        run.warnings = f.notes[:3]
