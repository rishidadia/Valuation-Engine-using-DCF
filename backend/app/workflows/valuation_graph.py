"""LangGraph valuation workflow — sequences the 12 agents.

    START → research → data → validation → historical → forecast → wacc
          → fcf → dcf → sensitivity → comparables → audit
          → [blocked notice if FAIL] → report → END

LLM agents never compute numbers; every stage delegates to services/valuation
functions. The graph owns orchestration, ordering and conditional routing.
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..agents import (
    audit as audit_agent,
    company_research as research_agent,
    comparables as comparables_agent,
    dcf as dcf_agent,
    fcf as fcf_agent,
    financial_data as data_agent,
    forecasting as forecast_agent,
    historical_analysis as historical_agent,
    report as report_agent,
    sensitivity as sensitivity_agent,
    validation as validation_agent,
    wacc as wacc_agent,
)
from ..services.engine import PipelineContext

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    ctx: PipelineContext


def _node(agent_run_fn):
    async def node(state: GraphState) -> GraphState:
        ctx = state["ctx"]
        await agent_run_fn(ctx)
        return {"ctx": ctx}

    return node


async def _blocked_notice(state: GraphState) -> GraphState:
    ctx = state["ctx"]
    if ctx.audit and not ctx.audit.can_finalize:
        from ..schemas.common import AgentRun
        ctx.agents.append(AgentRun(
            key="finalize", agent="Valuation Gate", status="failed",
            action="Decide whether the valuation may be marked complete",
            result="Final valuation BLOCKED by audit failures",
            warnings=list(ctx.audit.blocking_issues),
        ))
        ctx.errors.append({
            "code": "audit_blocked",
            "detail": "Final valuation cannot be marked complete: "
                      + "; ".join(ctx.audit.blocking_issues),
        })
    return {"ctx": ctx}


def _route_after_audit(state: GraphState) -> str:
    ctx = state["ctx"]
    if ctx.audit is None or ctx.audit.can_finalize:
        return "ok"
    return "blocked"


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("research", _node(research_agent.run))
    g.add_node("data", _node(data_agent.run))
    g.add_node("validation", _node(validation_agent.run))
    g.add_node("historical", _node(historical_agent.run))
    g.add_node("forecast", _node(forecast_agent.run))
    g.add_node("wacc", _node(wacc_agent.run))
    g.add_node("fcf", _node(fcf_agent.run))
    g.add_node("dcf", _node(dcf_agent.run))
    g.add_node("sensitivity", _node(sensitivity_agent.run))
    g.add_node("comparables", _node(comparables_agent.run))
    g.add_node("audit", _node(audit_agent.run))
    g.add_node("blocked_notice", _blocked_notice)
    g.add_node("report", _node(report_agent.run))

    g.add_edge(START, "research")
    for a, b in (
        ("research", "data"), ("data", "validation"), ("validation", "historical"),
        ("historical", "forecast"), ("forecast", "wacc"), ("wacc", "fcf"),
        ("fcf", "dcf"), ("dcf", "sensitivity"), ("sensitivity", "comparables"),
        ("comparables", "audit"),
    ):
        g.add_edge(a, b)

    g.add_conditional_edges(
        "audit",
        _route_after_audit,
        {"ok": "report", "blocked": "blocked_notice"},
    )
    g.add_edge("blocked_notice", "report")
    g.add_edge("report", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_valuation_workflow(ctx: PipelineContext) -> PipelineContext:
    """Execute the full agent graph over the pipeline context."""
    graph = get_graph()
    final: GraphState = await graph.ainvoke({"ctx": ctx})
    return final["ctx"]
