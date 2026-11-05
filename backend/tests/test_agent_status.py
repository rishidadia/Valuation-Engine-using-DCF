"""agent_run() must not overwrite a status the agent set deliberately."""
from types import SimpleNamespace

from app.agents.base import agent_run


def _ctx():
    return SimpleNamespace(agents=[])


def test_explicit_failed_status_is_preserved():
    ctx = _ctx()
    with agent_run(ctx, "audit", "Audit Agent", "checks") as run:
        run.status = "failed"
        run.result = "FAIL: 2 blocking issues"
    assert run.status == "failed"
    assert run.result == "FAIL: 2 blocking issues"


def test_explicit_skipped_status_is_preserved():
    ctx = _ctx()
    with agent_run(ctx, "comparables", "Comparables Agent", "peers") as run:
        run.status = "skipped"
    assert run.status == "skipped"


def test_explicit_success_is_preserved_even_with_warnings():
    ctx = _ctx()
    with agent_run(ctx, "data", "Data Agent", "fetch") as run:
        run.status = "success"
        run.warnings = ["minor provider gap"]
    assert run.status == "success"
    assert run.warnings == ["minor provider gap"]


def test_default_status_is_still_inferred():
    ctx = _ctx()
    with agent_run(ctx, "research", "Research Agent", "context") as run:
        pass
    assert run.status == "success"

    ctx2 = _ctx()
    with agent_run(ctx2, "data", "Data Agent", "fetch") as run2:
        run2.warnings = ["provider gap"]
    assert run2.status == "warning"


def test_failure_is_recorded_and_reraised():
    ctx = _ctx()
    try:
        with agent_run(ctx, "wacc", "WACC Agent", "discount rate") as run:
            raise ValueError("boom")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("exception was swallowed")
    assert run.status == "failed"
    assert "boom" in run.result
