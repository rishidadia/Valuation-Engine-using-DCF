"""Agent 4 — Historical Analysis Agent.

Computes growth/margin ratios, separates FACTS from INTERPRETATION from
ASSUMPTIONS (the separation is produced by the historical service).
"""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_historical
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "historical", "Historical Analysis Agent",
                   "Revenue growth, margins, tax rate, D&A/CapEx/NWC intensity, trends") as run:
        stage_historical(ctx)
        h = ctx.historical
        if h is None or not h.rows:
            run.status = "failed"
            run.result = "no historical periods to analyse"
            run.warnings.append("Historical analysis unavailable — check data ingestion.")
            return
        run.result = (
            f"{len(h.rows)} periods analysed; {len(h.facts)} facts, "
            f"{len(h.interpretation)} interpretation note(s), "
            f"{len(h.proposed_assumptions)} proposed assumptions"
        )
        cagr = h.summary.get("revenue_cagr")
        if cagr and cagr.value is not None:
            run.result += f"; revenue CAGR {cagr.value:.1%}"
        run.warnings = [a.note for a in h.proposed_assumptions
                        if a.note and "NOT DERIVABLE" in a.note]
