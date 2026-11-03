"""Agent 7 — FCF Agent: unlevered FCF schedule with per-year components."""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_fcf
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "fcf", "FCF Agent",
                   "UFCF = EBIT×(1−T) + D&A − CapEx − ΔNWC for every forecast year") as run:
        stage_fcf(ctx)
        s = ctx.fcf
        first, last = s.years[0], s.years[-1]
        run.result = (
            f"{len(s.years)} years: FCF {first.fcf.value:,.0f} → {last.fcf.value:,.0f}"
            + (f" (CAGR {s.fcf_cagr:.1%})" if s.fcf_cagr is not None else "")
            + f"; discounting at {ctx.wacc.wacc.value:.2%}"
        )
        neg = [y.period for y in s.years if (y.fcf.value or 0) < 0]
        if neg:
            run.warnings.append(f"Negative FCF in {', '.join(neg)}")
        run.warnings.extend(s.notes[:2])
