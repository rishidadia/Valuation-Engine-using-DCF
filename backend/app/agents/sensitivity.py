"""Agent 9 — Sensitivity Agent: two-way tables, tornado, scenario switching."""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_scenarios, stage_sensitivity
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "sensitivity", "Sensitivity Agent",
                   "WACC×growth, WACC×exit multiple tables; input swings; scenarios") as run:
        stage_sensitivity(ctx)
        stage_scenarios(ctx)
        parts = []
        if ctx.sensitivity:
            total_cells = sum(len(r) for t in ctx.sensitivity.tables for r in t.matrix)
            defined = sum(1 for t in ctx.sensitivity.tables for r in t.matrix for v in r if v is not None)
            parts.append(f"{len(ctx.sensitivity.tables)} tables ({defined}/{total_cells} cells defined)")
            parts.append(f"{len(ctx.sensitivity.tornado)} input swings")
        if ctx.scenarios:
            parts.append(f"{len(ctx.scenarios.scenarios)} scenarios ({ctx.scenarios.active} active)")
        run.result = "; ".join(parts) or "sensitivity skipped"
        if ctx.sensitivity:
            run.warnings = ctx.sensitivity.notes[:2]
        if ctx.scenarios:
            for s in ctx.scenarios.scenarios:
                if not s.valid:
                    run.warnings.append(f"{s.label}: {s.issue}")
