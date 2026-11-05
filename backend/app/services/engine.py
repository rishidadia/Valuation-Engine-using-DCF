"""Pipeline engine — stage functions and the shared compute closure.

Stages are plain Python functions; the LangGraph workflow sequences them via
agents. Sensitivity/scenarios re-run `make_compute` closures so every number
reported anywhere comes from identical math.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.errors import AppError, MissingDataError
from ..schemas.common import AgentRun, Assumption, AuditResult, CheckStatus, SourceRecord
from ..schemas.company import CompanyInfo, PeriodData
from ..schemas.valuation import (
    ComparablesResult, DcfResult, FcfSchedule, ForecastResult,
    HistoricalAnalysis, ReportDoc, ScenarioComparison, SensitivityResult,
    ValuationSummary, ValuationView, WaccCalculation,
)
from ..data.providers.base import MarketSnapshot
from ..schemas.valuation import ValuationOptions
from . import assumptions as assumptions_svc
from . import audit as audit_svc
from . import comparables as comparables_svc
from . import report as report_svc
from . import sensitivity as sensitivity_svc
from . import scenarios as scenarios_svc
from .core import CoreResult, compute_core, run_dcf, run_fcf, run_forecast, run_wacc
from .historical import analyze, normalize_signs


@dataclass
class PipelineContext:
    """Everything a run needs and produces."""

    company: CompanyInfo
    periods: list[PeriodData]
    market: MarketSnapshot = field(default_factory=MarketSnapshot)
    options: ValuationOptions = field(default_factory=ValuationOptions)
    overrides: dict[str, float] = field(default_factory=dict)
    excel_values: dict[str, float] = field(default_factory=dict)
    debt_instruments: list[dict] = field(default_factory=list)
    provider_missing: list[str] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    peers: list[Any] = field(default_factory=list)  # list[PeerMetrics]
    custom_scenario: dict[str, float] = field(default_factory=dict)
    active_scenario: str = "base"

    # artifacts
    historical: HistoricalAnalysis | None = None
    assumptions: list[Assumption] = field(default_factory=list)
    effective_values: dict[str, float | None] = field(default_factory=dict)
    forecast: ForecastResult | None = None
    wacc: WaccCalculation | None = None
    fcf: FcfSchedule | None = None
    dcf: DcfResult | None = None
    sensitivity: SensitivityResult | None = None
    scenarios: ScenarioComparison | None = None
    comparables: ComparablesResult | None = None
    audit: AuditResult | None = None
    report: ReportDoc | None = None
    agents: list[AgentRun] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def private(self) -> bool:
        return not self.company.is_public

    @property
    def base_values(self) -> dict[str, float | None]:
        return assumptions_svc.get_values(self.assumptions)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def stage_sign_normalisation(ctx: PipelineContext) -> None:
    ctx.warnings.extend(normalize_signs(ctx.periods))


def stage_historical(ctx: PipelineContext) -> None:
    ctx.historical = analyze(ctx.periods, private=ctx.private)


def stage_assumptions(ctx: PipelineContext) -> None:
    if ctx.historical is None:
        stage_historical(ctx)
    from ..core.config import settings
    ctx.assumptions = assumptions_svc.build_assumptions(
        ctx.historical, ctx.periods, ctx.market,
        private=ctx.private, excel_values=ctx.excel_values,
        default_rf=settings.default_risk_free_rate,
    )
    if ctx.overrides:
        assumptions_svc.apply_overrides(ctx.assumptions, ctx.overrides)


def merge_values(assumptions: list[Assumption],
                 overrides: dict[str, float] | None = None,
                 extra: dict[str, float] | None = None) -> dict[str, float | None]:
    values = assumptions_svc.get_values(assumptions)
    for source in (overrides, extra):
        if source:
            values.update(source)
    return values


def make_compute(ctx: PipelineContext):
    """Closure used by sensitivity + scenarios (same math as the main run)."""

    def compute(overrides: dict[str, float] | None = None, *,
                forced_wacc: float | None = None,
                forced_terminal: str | None = None,
                scenario_values: dict[str, float] | None = None) -> CoreResult:
        values = scenario_values if scenario_values is not None else merge_values(
            ctx.assumptions, overrides)
        options = ctx.options
        if forced_terminal:
            options = options.model_copy(update={"terminal_method": forced_terminal})
        return compute_core(
            ctx.periods, values, options,
            debt_instruments=ctx.debt_instruments,
            peers=ctx.peers, private=ctx.private,
            forced_wacc=forced_wacc,
            growth_overridden=_growth_is_user(ctx),
        )

    return compute


def active_values(ctx: PipelineContext) -> dict[str, float | None]:
    """Values actually used for the displayed valuation (scenario-aware)."""
    if ctx.active_scenario == "base" or not ctx.active_scenario:
        return ctx.base_values
    if ctx.active_scenario == "custom":
        return {**ctx.base_values, **(ctx.custom_scenario or {})}
    return scenarios_svc.apply_scenario(ctx.base_values, ctx.active_scenario)


def _growth_is_user(ctx: PipelineContext) -> bool:
    """True only when the revenue-growth driver came from the user
    (Excel input or an explicit override) — labels must never claim
    USER OVERRIDE for a model-derived value."""
    if "revenue_growth" in (ctx.overrides or {}):
        return True
    a = next((x for x in (ctx.assumptions or []) if x.key == "revenue_growth"), None)
    return a is not None and a.user_value is not None


def stage_forecast(ctx: PipelineContext) -> None:
    """Forecasting agent stage: deterministic driver-based projection."""
    values = active_values(ctx)
    ctx.effective_values = values
    ctx.forecast = run_forecast(ctx.periods, values, ctx.options,
                                growth_overridden=_growth_is_user(ctx))


def stage_wacc(ctx: PipelineContext) -> None:
    """WACC agent stage: CAPM, weights, discount rate."""
    values = ctx.effective_values or active_values(ctx)
    ctx.effective_values = values
    ctx.wacc = run_wacc(
        ctx.periods, values, ctx.options,
        debt_instruments=ctx.debt_instruments,
        peers=ctx.peers, private=ctx.private,
    )
    if ctx.wacc and ctx.wacc.cost_of_equity.value is not None:
        assumptions_svc.mark_calculated(
            ctx.assumptions, "cost_of_equity", ctx.wacc.cost_of_equity.value,
            "CAPM" if ctx.options.cost_of_equity_method == "capm" else "Manual expected return",
            ctx.wacc.capm_formula,
        )
    if ctx.wacc and ctx.wacc.beta.value is not None and ctx.options.beta_method == "comparables":
        assumptions_svc.mark_calculated(
            ctx.assumptions, "beta", ctx.wacc.beta.value,
            "Comparable companies (Hamada unlever/relever)",
            "; ".join(d.note or "" for d in ctx.wacc.beta_details[:1]) or None,
        )


def stage_fcf(ctx: PipelineContext) -> None:
    """FCF agent stage: component-by-component unlevered FCF."""
    values = ctx.effective_values or active_values(ctx)
    ctx.fcf = run_fcf(
        ctx.forecast, values.get("tax_rate"), ctx.wacc.wacc.value,
        convention=ctx.options.discount_convention,
    )


def stage_dcf(ctx: PipelineContext) -> None:
    """DCF agent stage: discounting, terminal value, equity bridge."""
    values = ctx.effective_values or active_values(ctx)
    ctx.dcf = run_dcf(
        ctx.fcf, wacc=ctx.wacc.wacc.value, values=values,
        periods=ctx.periods, options=ctx.options,
    )


def stage_core(ctx: PipelineContext) -> None:
    """Forecast + WACC + FCF + DCF in one deterministic pass."""
    stage_forecast(ctx)
    stage_wacc(ctx)
    stage_fcf(ctx)
    stage_dcf(ctx)


def stage_sensitivity(ctx: PipelineContext) -> None:
    if not ctx.options.run_sensitivity or ctx.dcf is None:
        return
    if not ctx.dcf.valid:
        ctx.warnings.append("Sensitivity skipped: base DCF is invalid.")
        return
    compute = make_compute(ctx)
    ctx.sensitivity = sensitivity_svc.build_sensitivity(
        compute, ctx.effective_values or ctx.base_values, ctx.dcf)


def stage_scenarios(ctx: PipelineContext) -> None:
    compute = make_compute(ctx)
    ctx.scenarios = scenarios_svc.evaluate_scenarios(
        compute, ctx.base_values,
        active=ctx.active_scenario,
        custom_overrides=ctx.custom_scenario or None,
    )


def stage_comparables(ctx: PipelineContext) -> None:
    if not ctx.options.run_comparables:
        return
    ctx.comparables = comparables_svc.build_comparables(
        ctx.peers, ctx.periods,
        ctx.base_values.get("share_price"),
        ctx.base_values.get("shares_outstanding"),
        ctx.dcf,
    )


def stage_audit(ctx: PipelineContext) -> None:
    ctx.audit = audit_svc.run_audit(
        ctx.periods, ctx.forecast, ctx.wacc, ctx.fcf, ctx.dcf,
        ctx.effective_values or ctx.base_values, ctx.provider_missing,
        convention=ctx.options.discount_convention,
    )


def stage_report(ctx: PipelineContext) -> None:
    ctx.report = report_svc.build_report(
        ctx.company, ctx.periods, ctx.historical, ctx.assumptions,
        ctx.forecast, ctx.wacc, ctx.fcf, ctx.dcf, ctx.sensitivity,
        ctx.scenarios, ctx.comparables, ctx.audit, ctx.sources,
    )


def run_stages(ctx: PipelineContext, *, with_sensitivity: bool = True) -> None:
    """Deterministic ordering used when not going through LangGraph."""
    stage_sign_normalisation(ctx)
    stage_historical(ctx)
    stage_assumptions(ctx)
    stage_core(ctx)
    if with_sensitivity:
        stage_sensitivity(ctx)
    stage_scenarios(ctx)
    stage_comparables(ctx)
    stage_audit(ctx)
    stage_report(ctx)


# ---------------------------------------------------------------------------
# View assembly
# ---------------------------------------------------------------------------

def build_view(ctx: PipelineContext, *, valuation_id: str | None = None) -> ValuationView:
    dcf = ctx.dcf
    summary = ValuationSummary(
        id=valuation_id,
        status=("complete" if (ctx.audit and ctx.audit.can_finalize)
                else "blocked" if ctx.audit else "draft"),
        company=ctx.company,
        created_at=datetime.now(timezone.utc),
        current_share_price=ctx.base_values.get("share_price"),
        implied_share_price=dcf.implied_share_price if dcf else None,
        upside_downside=dcf.upside_downside if dcf else None,
        enterprise_value=dcf.enterprise_value if dcf else None,
        equity_value=dcf.equity_value if dcf else None,
        wacc=ctx.wacc.wacc.value if ctx.wacc else None,
        terminal_growth=dcf.terminal_growth if dcf else None,
        fcf_cagr=dcf.fcf_cagr if dcf else None,
        audit_status=(ctx.audit.status if ctx.audit else CheckStatus.PASS),
        blocked_reasons=(ctx.audit.blocking_issues if ctx.audit else []),
    )
    return ValuationView(
        summary=summary, company=ctx.company, options=ctx.options,
        historical_periods=ctx.periods,
        forecast=ctx.forecast, historical=ctx.historical, assumptions=ctx.assumptions,
        wacc=ctx.wacc, fcf=ctx.fcf, dcf=ctx.dcf, sensitivity=ctx.sensitivity,
        scenarios=ctx.scenarios, comparables=ctx.comparables, audit=ctx.audit,
        report=ctx.report, agents=ctx.agents, sources=ctx.sources,
        errors=ctx.errors + [{"code": "warning", "detail": w} for w in ctx.warnings],
    )


def recompute_view(ctx: PipelineContext, *, valuation_id: str | None = None) -> ValuationView:
    """Re-run stages after an assumptions/scenario change (no re-ingestion)."""
    try:
        run_stages(ctx)
    except AppError as exc:
        ctx.errors = [{"code": exc.code, "detail": exc.detail, "hint": exc.hint}]
        raise
    return build_view(ctx, valuation_id=valuation_id)
