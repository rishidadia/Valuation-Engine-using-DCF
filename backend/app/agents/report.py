"""Agent 11 — Report Agent: research-style report with typed provenance kinds.

Narrative paragraphs may be LLM-drafted; every number is injected from the
computed artifacts, never from the model.
"""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_report
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "report", "Report Agent",
                   "Assemble report sections with FACT/CALCULATION/ASSUMPTION tags") as run:
        stage_report(ctx)
        doc = ctx.report
        run.result = (
            f"{len(doc.sections)} sections, {len(doc.markdown):,} chars of markdown; "
            f"audit status {doc.audit_status.value}"
        )
        run.llm_used = doc.llm_used
        if doc.llm_used:
            run.result += "; narrative sections LLM-drafted (numbers are computed)"
