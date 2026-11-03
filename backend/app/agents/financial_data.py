"""Agent 2 — Financial Data Agent.

Retrieves/parses statements (ingest time), then normalizes: units, currency,
period alignment, original reported values preserved, missing data flagged.
"""
from __future__ import annotations

from ..data.providers.base import DataProvider, ProviderPayload
from ..schemas.common import AgentRun, SourceRecord
from ..schemas.company import CompanyInfo, MappingNote, PeriodData
from ..services.engine import PipelineContext
from .base import agent_run


async def ingest(provider: DataProvider, **kwargs) -> tuple[ProviderPayload, list[AgentRun], list[MappingNote]]:
    """Run a provider with agent bookkeeping (used by the upload/public endpoints)."""
    runs: list[AgentRun] = []
    ctx = _TempCtx(runs)
    with agent_run(ctx, "data", "Financial Data Agent",
                   f"Retrieve/parse statements via {provider.name} provider") as run:
        payload = await provider.fetch(**kwargs)
        units = {p.currency for p in payload.periods}
        run.result = (
            f"{len(payload.periods)} periods parsed ({', '.join(p.period for p in payload.periods[:6])}"
            f"{'…' if len(payload.periods) > 6 else ''}); currency {', '.join(sorted(units)) or 'n/a'}; "
            f"{sum(len(p.metrics) for p in payload.periods)} metric values mapped"
        )
        if payload.missing:
            run.warnings.append("Missing critical metrics: " + ", ".join(payload.missing))
        run.warnings.extend(payload.warnings[:6])
        run.sources = [s.name for s in payload.sources]
        mapping = getattr(provider, "mapping_notes", [])
    return payload, runs, list(mapping)


class _TempCtx:
    """Minimal shim so agent_run can record before a PipelineContext exists."""

    def __init__(self, sink: list[AgentRun]):
        self.agents = sink


async def run(ctx: PipelineContext) -> None:
    """Run-time pass: verify normalized data readiness and report gaps."""
    with agent_run(ctx, "data", "Financial Data Agent",
                   "Verify normalization: units, currency, periods, missing flags") as run:
        latest = ctx.periods[-1] if ctx.periods else None
        metric_count = sum(len(p.metrics) for p in ctx.periods)
        currencies = sorted({p.currency for p in ctx.periods})
        run.result = (
            f"{len(ctx.periods)} periods, {metric_count} values, currency {', '.join(currencies)}"
            + (f", latest {latest.period}" if latest else "")
        )
        if ctx.provider_missing:
            run.warnings.append(
                "Not provided by any source (flagged for manual entry): "
                + ", ".join(ctx.provider_missing))
        if len(currencies) > 1:
            run.warnings.append(f"Mixed currencies detected: {', '.join(currencies)}")
        ctx.errors = [e for e in ctx.errors]
