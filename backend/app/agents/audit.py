"""Agent 12 — Audit Agent: runs before final valuation; FAIL blocks completion."""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_audit
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "audit", "Audit Agent",
                   "Missing data, units, currencies, signs, WACC, TV, FCF, tax, double counting") as run:
        stage_audit(ctx)
        a = ctx.audit
        n_pass = sum(1 for c in a.checks if c.status.value == "PASS")
        n_warn = sum(1 for c in a.checks if c.status.value == "WARNING")
        n_fail = sum(1 for c in a.checks if c.status.value == "FAIL")
        run.result = (
            f"{a.status.value}: {n_pass} pass, {n_warn} warning, {n_fail} fail"
            + (" — finalization BLOCKED" if not a.can_finalize else " — valuation finalizable")
        )
        run.warnings = a.blocking_issues or [c.detail for c in a.checks
                                              if c.status.value == "WARNING"][:4]
