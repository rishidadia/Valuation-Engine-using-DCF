"""Agent 1 — Company Research Agent.

Identifies the company, confirms ticker/exchange/industry, records reporting
periods and source URLs + timestamps. Optional LLM enrichment for the
overview sentence only; all facts come from the provider payload.
"""
from __future__ import annotations

from ..core.llm import llm_complete
from ..services.engine import PipelineContext
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    company = ctx.company
    with agent_run(ctx, "research", "Company Research Agent",
                   "Identify company, ticker, industry, reporting periods, sources") as run:
        periods = ", ".join(p.period for p in ctx.periods) or "none"
        run.sources = [s.name for s in ctx.sources] or ([company.source] if company.source else [])

        facts = (
            f"Company: {company.name}; ticker: {company.ticker or 'private'}; "
            f"industry: {company.industry or 'unknown'}; periods: {periods}; "
            f"provider: {company.provider or company.source}."
        )
        overview, used = llm_complete(
            "You are a equity research analyst. Write 2 concise factual sentences "
            "about the company from ONLY the facts given. No advice, no forecasts.",
            facts,
        )
        run.llm_used = used
        if overview:
            company.description = overview
        run.result = (
            f"{company.name} ({company.ticker or 'private'}) — "
            f"{company.industry or 'industry unclassified'}; "
            f"{len(ctx.periods)} annual periods: {periods}"
        )
        if not ctx.periods:
            run.warnings.append("No reporting periods found — valuation will be blocked.")
        if company.source_url:
            run.sources.append(company.source_url)
