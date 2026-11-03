"""Agent 10 — Comparable Valuation Agent: peer multiples vs DCF (never forced)."""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_comparables
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "comparables", "Comparable Valuation Agent",
                   "EV/Revenue, EV/EBITDA, EV/EBIT, P/E vs DCF where peer data exists") as run:
        stage_comparables(ctx)
        c = ctx.comparables
        if c is None:
            run.status = "skipped"
            run.result = "comparables disabled for this run"
            return
        if c.status == "insufficient_data":
            run.status = "warning"
            run.result = "skipped — insufficient peer data (no multiples invented)"
            run.warnings = c.notes
            return
        medians = ", ".join(
            f"{m} {s['median']:.1f}x" for m, s in c.multiple_stats.items()
            if s.get("median"))
        run.result = f"{len(c.peers)} peers; median multiples: {medians}"
        if c.dcf_vs_comps:
            run.result += f"; DCF vs comps {c.dcf_vs_comps['spread']:+.1%}"
        run.warnings = c.notes[:2]
