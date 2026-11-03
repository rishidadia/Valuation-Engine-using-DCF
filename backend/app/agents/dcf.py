"""Agent 8 — DCF Agent: discounting, terminal value, EV/equity/price bridge."""
from __future__ import annotations

from ..services.engine import PipelineContext, stage_dcf
from .base import agent_run


async def run(ctx: PipelineContext) -> None:
    with agent_run(ctx, "dcf", "DCF Agent",
                   "PV of FCF, terminal value (both methods), EV → equity → price") as run:
        stage_dcf(ctx)
        d = ctx.dcf
        if not d.valid:
            run.status = "failed"
            run.result = f"DCF blocked: {d.issue}"
            run.warnings.append(d.issue or "DCF invalid")
            return
        price = f"{d.implied_share_price:,.2f}" if d.implied_share_price else "n/a (no shares)"
        run.result = (
            f"EV {d.enterprise_value:,.0f} → equity {d.equity_value:,.0f} → price {price}"
            + (f" ({d.upside_downside:+.1%} vs market)" if d.upside_downside is not None else "")
        )
        perp = next((m for m in d.terminal_methods if m.method == "perpetuity_growth"), None)
        if perp and perp.valid:
            run.result += f"; TV {perp.terminal_value:,.0f} ({perp.pv_terminal_value / d.enterprise_value:.0%} of EV)"
        run.warnings = list(d.warnings)
