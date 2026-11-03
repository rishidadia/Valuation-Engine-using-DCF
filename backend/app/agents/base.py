"""Shared agent scaffolding.

Agents expose status / action / result / warnings / sources only — never
chain-of-thought. Financial math always lives in services/valuation code.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from ..schemas.common import AgentRun

logger = logging.getLogger(__name__)


@contextmanager
def agent_run(ctx, key: str, agent: str, action: str):
    """Record an agent execution on the pipeline context."""
    run = AgentRun(
        key=key, agent=agent, status="running", action=action,
        started_at=datetime.now(timezone.utc),
    )
    ctx.agents.append(run)
    t0 = time.perf_counter()
    try:
        yield run
        run.status = "warning" if run.warnings else "success"
        if not run.result:
            run.result = "completed"
    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
        run.status = "failed"
        run.result = f"failed: {getattr(exc, 'detail', exc)}"
        logger.exception("Agent %s failed", key)
        raise
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = int((time.perf_counter() - t0) * 1000)
