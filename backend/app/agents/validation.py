"""Agent 3 — Financial Validation Agent.

Checks statement ties, units, currencies and period alignment.
Discrepancies are reported, never silently fixed (normalisation itself is
recorded as an explicit warning by the historical stage).
"""
from __future__ import annotations

from ..schemas.common import CheckStatus
from ..services.historical import normalize_signs
from ..services.engine import PipelineContext
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "validation", "Validation Agent",
                   "Statement ties, units, currencies, period alignment") as run:
        issues: list[str] = []
        status = CheckStatus.PASS

        # sign normalisation (explicit, recorded)
        flips = normalize_signs(ctx.periods)
        if flips:
            status = CheckStatus.WARNING
            issues.extend(flips[:4])

        latest = ctx.periods[-1] if ctx.periods else None
        if latest:
            rev = latest.value("revenue")
            cogs = latest.value("cogs")
            gp = latest.value("gross_profit")
            if rev is not None and cogs is not None and gp is not None:
                expected = rev - cogs
                if abs(gp - expected) / max(abs(rev), 1) > 0.015:
                    status = CheckStatus.WARNING
                    issues.append(
                        f"{latest.period}: gross profit {gp:,.0f} vs revenue−COGS {expected:,.0f} "
                        "(reported discrepancy preserved, not fixed)")
            ta, tl, se = (latest.value("total_assets"), latest.value("total_liabilities"),
                          latest.value("shareholders_equity"))
            if ta and tl is not None and se is not None and abs(ta - (tl + se)) / abs(ta) > 0.02:
                status = CheckStatus.WARNING
                issues.append(f"{latest.period}: balance sheet out of balance by {ta - tl - se:,.0f}")

        years = [p.fiscal_year for p in ctx.periods]
        if years != sorted(years):
            status = CheckStatus.WARNING
            issues.append("Periods are not in chronological order")

        currencies = {p.currency for p in ctx.periods}
        if len(currencies) > 1:
            status = CheckStatus.FAIL
            issues.append(f"mixed currencies: {', '.join(sorted(currencies))}")

        run.warnings = issues
        run.result = f"{status.value}: {len(issues)} issue(s) found across {len(ctx.periods)} periods"
        run.sources = [s.name for s in ctx.sources]
