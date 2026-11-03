"""Audit blocking + error-handling tests (spec §21).

WACC <= terminal growth must stop terminal-value calculation and block the
final valuation from being marked complete — never silently continue.
"""
from datetime import date

import pytest

from app.core.errors import MissingDataError, TerminalValueError, ValidationError
from app.schemas.api import ValuationOptions
from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.schemas.company import CompanyInfo, PeriodData
from app.services.engine import PipelineContext, build_view, run_stages


def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.USER_INPUT, status=ValueStatus.USER_DATA)


def _periods(years=4, revenue=100e6) -> list[PeriodData]:
    out, rev = [], revenue
    for i, y in enumerate(range(2022, 2022 + years)):
        if i:
            rev *= 1.08
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 12, 31), metrics={
            "revenue": _sv(rev), "cogs": _sv(rev * .6), "gross_profit": _sv(rev * .4),
            "ebit": _sv(rev * .18), "ebt": _sv(rev * .17), "income_tax_expense": _sv(rev * .04),
            "net_income": _sv(rev * .13), "da": _sv(rev * .03), "capex": _sv(rev * .04),
            "cash": _sv(50e6), "total_debt": _sv(120e6), "short_term_debt": _sv(20e6),
            "long_term_debt": _sv(100e6),
            "shares_outstanding": _sv(10e6, Unit.COUNT),
            "accounts_receivable": _sv(rev * .12), "inventory": _sv(rev * .10),
            "accounts_payable": _sv(rev * .08),
        }))
    return out


def _ctx(**kw) -> PipelineContext:
    company = CompanyInfo(name="T", ticker="T", is_public=False, source="test")
    ctx = PipelineContext(company=company, periods=_periods(),
                          options=ValuationOptions(run_comparables=False,
                                                   capital_structure_method="target"),
                          overrides={"beta": 1.1, "target_de": 0.3, "share_price": 20.0},
                          **kw)
    return ctx


def test_wacc_below_terminal_growth_blocks_valuation():
    ctx = _ctx()
    ctx.overrides = {**ctx.overrides, "terminal_growth": 0.10}  # >> WACC
    run_stages(ctx)
    perp = next(m for m in ctx.dcf.terminal_methods if m.method == "perpetuity_growth")
    assert perp.valid is False
    assert "strictly below WACC" in perp.issue
    # an explicit fallback is used and clearly announced — never a silent g-based TV
    assert any("unavailable" in w for w in ctx.dcf.warnings)
    assert ctx.dcf.selected_method == "exit_multiple"
    # ...but the audit still refuses to finalize a run whose requested method broke
    assert ctx.audit.can_finalize is False
    assert ctx.audit.status.value == "FAIL"
    assert any("erminal" in b for b in ctx.audit.blocking_issues)
    view = build_view(ctx)
    assert view.summary.status == "blocked"
    assert view.summary.blocked_reasons


def test_missing_beta_blocks_run_explicitly():
    ctx = _ctx()
    ctx.overrides = {"target_de": 0.3, "share_price": 20.0}  # no beta anywhere
    with pytest.raises(MissingDataError) as ei:
        run_stages(ctx)
    assert "Beta" in str(ei.value.detail)
    assert ei.value.hint  # actionable guidance, no silent default


def test_negative_tax_rate_rejected():
    from app.valuation import calculate_wacc
    with pytest.raises(ValidationError):
        calculate_wacc(0.8, 0.2, 0.10, 0.05, -0.05)


def test_mixed_currency_fails_audit():
    ctx = _ctx()
    ctx.periods[-1].currency = "EUR"
    run_stages(ctx)
    assert ctx.audit.can_finalize is False
    assert any("currency" in b.lower() for b in ctx.audit.blocking_issues)


def test_unknown_override_key_rejected():
    from app.services.assumptions import apply_overrides, build_assumptions
    from app.services.historical import analyze
    ctx = _ctx()
    hist = analyze(ctx.periods, private=True)
    assumptions = build_assumptions(hist, ctx.periods, ctx.market, private=True)
    with pytest.raises(ValidationError) as ei:
        apply_overrides(assumptions, {"nonsense_key": 1.0})
    assert "Unknown assumption" in str(ei.value.detail)


def test_report_marks_audit_and_disclaimer():
    ctx = _ctx()
    run_stages(ctx)
    doc = ctx.report
    assert "highly sensitive to assumptions" in doc.disclaimer
    kinds = {s.kind for s in doc.sections}
    assert {"FACT", "CALCULATION", "ASSUMPTION"} <= kinds
    assert "Audit" in " ".join(s.heading for s in doc.sections)
