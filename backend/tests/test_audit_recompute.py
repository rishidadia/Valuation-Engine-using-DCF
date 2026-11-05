"""The audit must rebuild each identity, not just range-check stored numbers.

These tests prove that CAPM, WACC, discount factors, terminal value, EV, the
equity bridge and the implied price are independently recomputed, and that a
tampered stored result fails the audit and blocks finalization.
"""
from datetime import date

from app.schemas.api import ValuationOptions
from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.schemas.company import CompanyInfo, PeriodData
from app.services import audit as audit_svc
from app.services.engine import PipelineContext, run_stages


def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.USER_INPUT, status=ValueStatus.USER_DATA)


def _periods(years: int = 4) -> list[PeriodData]:
    out, rev = [], 100e6
    for i, y in enumerate(range(2022, 2022 + years)):
        if i:
            rev *= 1.08
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 12, 31), metrics={
            "revenue": _sv(rev), "cogs": _sv(rev * .6), "gross_profit": _sv(rev * .4),
            "ebit": _sv(rev * .18), "ebt": _sv(rev * .17),
            "income_tax_expense": _sv(rev * .04), "net_income": _sv(rev * .13),
            "da": _sv(rev * .03), "capex": _sv(rev * .04),
            "cash": _sv(50e6), "total_debt": _sv(120e6),
            "short_term_debt": _sv(20e6), "long_term_debt": _sv(100e6),
            "shares_outstanding": _sv(10e6, Unit.COUNT),
        }))
    return out


def _ctx() -> PipelineContext:
    return PipelineContext(
        company=CompanyInfo(name="T", ticker="T", is_public=False, source="test"),
        periods=_periods(),
        options=ValuationOptions(run_comparables=False, run_sensitivity=False,
                                 capital_structure_method="target"),
        overrides={"beta": 1.1, "target_de": 0.3, "share_price": 20.0},
    )


def _checks(audit) -> dict:
    return {c.name: c for c in audit.checks}


def test_audit_recomputes_the_full_chain():
    ctx = _ctx()
    run_stages(ctx)
    checks = _checks(ctx.audit)

    expected = [
        "CAPM recomputation", "WACC recomputation", "Discount factors",
        "Terminal value recomputation", "PV of terminal value",
        "Enterprise value recomputation", "Equity bridge recomputation",
        "Implied price recomputation",
    ]
    for name in expected:
        assert name in checks, f"missing audit check {name}: {sorted(checks)}"
        assert checks[name].status.value == "PASS", (name, checks[name].detail)
    assert ctx.audit.can_finalize


def test_tampered_wacc_fails_audit():
    ctx = _ctx()
    run_stages(ctx)
    ctx.wacc.wacc.value = ctx.wacc.wacc.value + 0.01

    audit = audit_svc.run_audit(
        ctx.periods, ctx.forecast, ctx.wacc, ctx.fcf, ctx.dcf,
        ctx.effective_values, ctx.provider_missing,
        convention=ctx.options.discount_convention,
    )
    checks = _checks(audit)
    assert checks["WACC recomputation"].status.value == "FAIL"
    assert audit.can_finalize is False


def test_tampered_enterprise_value_fails_audit():
    ctx = _ctx()
    run_stages(ctx)
    ctx.dcf.enterprise_value = ctx.dcf.enterprise_value + 1e6

    audit = audit_svc.run_audit(
        ctx.periods, ctx.forecast, ctx.wacc, ctx.fcf, ctx.dcf,
        ctx.effective_values, ctx.provider_missing,
        convention=ctx.options.discount_convention,
    )
    checks = _checks(audit)
    assert checks["Enterprise value recomputation"].status.value == "FAIL"
    assert checks["Equity bridge recomputation"].status.value == "FAIL"
    assert audit.can_finalize is False
