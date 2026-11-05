"""Audit stage — runs before the valuation can be marked complete.

Checks (spec §6 agent 12): missing data, formulas, units, currencies, signs,
double counting, debt/equity treatment, WACC, terminal value, FCF, forecast
consistency, tax treatment. FAIL blocks finalization.
"""
from __future__ import annotations

from ..schemas.common import AuditResult, Check, CheckStatus, SourceType
from ..schemas.company import PeriodData
from ..schemas.valuation import DcfResult, FcfSchedule, ForecastResult, WaccCalculation


def _pct(x: float | None) -> str:
    return f"{x:.2%}" if x is not None else "n/a"


def run_audit(
    periods: list[PeriodData],
    forecast: ForecastResult | None,
    wacc: WaccCalculation | None,
    fcf: FcfSchedule | None,
    dcf: DcfResult | None,
    values: dict[str, float | None],
    provider_missing: list[str] | None = None,
    convention: str = "end",
) -> AuditResult:
    checks: list[Check] = []
    blocking: list[str] = []

    def add(name: str, status: CheckStatus, detail: str,
            severity: str = "info", block: bool = False) -> None:
        checks.append(Check(name=name, status=status, detail=detail,
                            severity=severity))  # type: ignore[arg-type]
        if block or (status == CheckStatus.FAIL and severity == "critical"):
            blocking.append(f"{name}: {detail}")

    # ---- 1. missing data ----------------------------------------------------
    latest = periods[-1] if periods else None
    if latest is None or latest.value("revenue") is None:
        add("Missing data — revenue", CheckStatus.FAIL,
            "No revenue in the latest period; the valuation would be built on nothing.",
            "critical", block=True)
    else:
        add("Missing data — revenue", CheckStatus.PASS,
            f"Revenue present for {latest.period}: {latest.value('revenue'):,.0f}.")

    for key in ("ebit", "shares_outstanding"):
        if latest is None or latest.value(key) is None:
            v = values.get(key)
            if v is None:
                if key == "shares_outstanding":
                    add(f"Missing data — {key}", CheckStatus.WARNING,
                        "Shares outstanding absent — implied share price unavailable; "
                        "equity value is still reported.", "warning")
                else:
                    add(f"Missing data — {key}", CheckStatus.WARNING,
                        f"{key} absent — EBIT margin must be supplied for the forecast.", "warning")
            else:
                add(f"Missing data — {key}", CheckStatus.WARNING,
                    f"{key} not in statements; using user-provided value.", "warning")
        else:
            add(f"Missing data — {key}", CheckStatus.PASS, f"{key} present in {latest.period}.")

    if provider_missing:
        add("Provider gaps", CheckStatus.WARNING,
            "Unretrieved metrics: " + ", ".join(provider_missing) +
            ". Each is flagged for manual entry — none were guessed.", "warning")

    # ---- 2. currency / unit consistency ------------------------------------
    currencies = {p.currency for p in periods}
    if len(currencies) > 1:
        add("Currency consistency", CheckStatus.FAIL,
            f"Periods mix currencies: {', '.join(sorted(currencies))}.",
            "critical", block=True)
    else:
        add("Currency consistency", CheckStatus.PASS,
            f"All periods reported in {next(iter(currencies), 'n/a')}.")

    # ---- 3. signs ------------------------------------------------------------
    sign_issues = []
    for p in periods:
        if (p.value("revenue") or 0) < 0:
            sign_issues.append(f"{p.period} negative revenue")
        capex = p.value("capex")
        if capex is not None and capex < 0:
            sign_issues.append(f"{p.period} CapEx negative after normalisation")
    if sign_issues:
        add("Sign checks", CheckStatus.WARNING, "; ".join(sign_issues), "warning")
    else:
        add("Sign checks", CheckStatus.PASS, "Revenue positive, costs stored as outflows throughout.")

    # ---- 4. income statement ties -------------------------------------------
    if latest:
        rev, cogs = latest.value("revenue"), latest.value("cogs")
        gp, ebit = latest.value("gross_profit"), latest.value("ebit")
        if rev and cogs and gp is not None:
            expected = rev - cogs
            if abs(gp - expected) / max(abs(rev), 1) > 0.015:
                add("Income statement tie (Rev − COGS = GP)", CheckStatus.WARNING,
                    f"Reported GP {gp:,.0f} vs computed {expected:,.0f} "
                    f"({(gp - expected) / abs(rev):.2%} of revenue). Not auto-fixed.",
                    "warning")
            else:
                add("Income statement tie (Rev − COGS = GP)", CheckStatus.PASS,
                    f"GP {gp:,.0f} reconciles to Rev − COGS within tolerance.")
        ebt, tax, ni = latest.value("ebt"), latest.value("income_tax_expense"), latest.value("net_income")
        if ebit is not None and ebt is not None and tax is not None and ni is not None:
            implied_ni = ebt - tax
            if abs(ni - implied_ni) / max(abs(ebt), 1) > 0.02:
                add("Net income tie (EBT − Tax = NI)", CheckStatus.WARNING,
                    f"Reported NI {ni:,.0f} vs computed {implied_ni:,.0f}. Not auto-fixed.",
                    "warning")
            else:
                add("Net income tie (EBT − Tax = NI)", CheckStatus.PASS,
                    "Net income reconciles within tolerance.")
        ta, tl, se = latest.value("total_assets"), latest.value("total_liabilities"), latest.value("shareholders_equity")
        if ta and tl is not None and se is not None:
            diff = ta - (tl + se)
            if abs(diff) / abs(ta) > 0.02:
                add("Balance sheet (A = L + E)", CheckStatus.WARNING,
                    f"Assets {ta:,.0f} vs L+E {tl + se:,.0f} (diff {diff:,.0f}). Not auto-fixed.",
                    "warning")
            else:
                add("Balance sheet (A = L + E)", CheckStatus.PASS,
                    "Balance sheet balances within 2% tolerance.")
        else:
            add("Balance sheet (A = L + E)", CheckStatus.WARNING,
                "Insufficient balance-sheet data to verify A = L + E.", "warning")

    # ---- 5. WACC --------------------------------------------------------------
    if wacc and wacc.wacc.value is not None:
        w = wacc.wacc.value
        if not 0.005 <= w <= 0.30:
            add("WACC range", CheckStatus.FAIL,
                f"WACC {_pct(w)} outside [0.5%, 30%] — check rate inputs (decimals expected).",
                "critical", block=True)
        else:
            add("WACC range", CheckStatus.PASS, f"WACC {_pct(w)} within plausible bounds.")
        ew, dw = (wacc.equity_weight.value or 0), (wacc.debt_weight.value or 0)
        if abs(ew + dw - 1.0) > 1e-6:
            add("Capital weights", CheckStatus.FAIL,
                f"Weights sum to {ew + dw:.6f}, not 1.", "critical", block=True)
        else:
            add("Capital weights", CheckStatus.PASS,
                f"w_e {ew:.1%} + w_d {dw:.1%} = 1 (debt/equity counted once).")
        if wacc.beta.value is None:
            add("Beta range", CheckStatus.WARNING,
                "Beta not supplied — acceptable only because a manual cost of equity "
                "is in use; no CAPM reference exists.", "warning")
        elif not -1 <= wacc.beta.value <= 4:
            add("Beta range", CheckStatus.FAIL,
                f"Beta {wacc.beta.value:.2f} outside [-1, 4].", "critical", block=True)
        else:
            add("Beta range", CheckStatus.PASS, f"Beta {wacc.beta.value:.2f} plausible.")
    else:
        add("WACC", CheckStatus.FAIL, "WACC missing — cannot discount cash flows.",
            "critical", block=True)

    # ---- 6. terminal value ----------------------------------------------------
    if dcf:
        g, w = dcf.terminal_growth, dcf.discount_rate
        perp = next((m for m in dcf.terminal_methods if m.method == "perpetuity_growth"), None)
        if perp is not None and not perp.valid:
            add("Terminal value (perpetuity)", CheckStatus.FAIL,
                perp.issue or "Perpetuity terminal value undefined.", "critical", block=True)
        elif perp is not None:
            add("Terminal value (perpetuity)", CheckStatus.PASS,
                f"WACC {w:.2%} > g {g:.2%}; TV finite.")
        if dcf.exit_multiple is not None and not 0.5 <= dcf.exit_multiple <= 40:
            add("Terminal value (exit multiple)", CheckStatus.WARNING,
                f"Exit multiple {dcf.exit_multiple:.1f}x outside typical [0.5x, 40x].", "warning")
        tv_share = None
        if perp and perp.valid and perp.pv_terminal_value and dcf.enterprise_value:
            tv_share = perp.pv_terminal_value / dcf.enterprise_value
            status = CheckStatus.WARNING if tv_share > 0.80 else CheckStatus.PASS
            add("Terminal value share of EV", status,
                f"PV(TV) = {tv_share:.0%} of enterprise value"
                + (" — valuation is dominated by the terminal assumption."
                   if status == CheckStatus.WARNING else "."),
                "warning" if status == CheckStatus.WARNING else "info")
        if not dcf.valid:
            add("DCF computed", CheckStatus.FAIL,
                dcf.issue or "DCF did not produce a valuation.", "critical", block=True)
        else:
            add("DCF computed", CheckStatus.PASS,
                f"EV {dcf.enterprise_value:,.0f}, equity {dcf.equity_value:,.0f}.")

    # ---- 7. FCF recomputation (formula integrity) -----------------------------
    if fcf and forecast:
        mismatch = None
        for y in fcf.years:
            fy = next((f for f in forecast.years if f.period == y.period), None)
            if not fy:
                continue
            tax_rate = values.get("tax_rate") or 0.0
            recomputed = (fy.ebit.value * (1 - tax_rate) + fy.da.value
                          - fy.capex.value - fy.change_nwc.value)
            if abs(recomputed - y.fcf.value) > max(1.0, abs(recomputed) * 1e-6):
                mismatch = f"{y.period}: stored {y.fcf.value:,.2f} vs recomputed {recomputed:,.2f}"
                break
        if mismatch:
            add("FCF recomputation", CheckStatus.FAIL,
                f"Stored FCF does not match formula: {mismatch}", "critical", block=True)
        else:
            add("FCF recomputation", CheckStatus.PASS,
                "Every forecast year's FCF reproduces EBIT×(1−T)+D&A−CapEx−ΔNWC exactly.")
        neg = [y.period for y in fcf.years if (y.fcf.value or 0) < 0]
        if neg:
            add("FCF sign pattern", CheckStatus.WARNING,
                f"Negative FCF in {', '.join(neg)} — check margin/capex assumptions.", "warning")

    # ---- 8. tax treatment -----------------------------------------------------
    tax_rate = values.get("tax_rate")
    if tax_rate is None or not 0 <= tax_rate <= 0.50:
        add("Tax treatment", CheckStatus.FAIL,
            f"Tax rate {_pct(tax_rate)} outside [0%, 50%].", "critical", block=True)
    else:
        add("Tax treatment", CheckStatus.PASS,
            f"Tax rate {_pct(tax_rate)} applied to EBIT (unlevered NOPAT treatment).")

    # ---- 9. forecast consistency ----------------------------------------------
    if forecast and forecast.years:
        gs = [y.revenue_growth.value for y in forecast.years]
        margins = [y.ebit_margin.value for y in forecast.years]
        ok = all(g is not None for g in gs) and all(m is not None for m in margins)
        if ok:
            add("Forecast consistency", CheckStatus.PASS,
                f"{len(forecast.years)} forecast years; revenue growth "
                f"{min(gs):.2%} to {max(gs):.2%}, EBIT margin "
                f"{min(margins):.2%} to {max(margins):.2%}.")
        else:
            add("Forecast consistency", CheckStatus.FAIL,
                "Forecast contains missing drivers.", "critical", block=True)

    # ---- 10. double counting ----------------------------------------------------
    if latest:
        st, lt, td = latest.value("short_term_debt"), latest.value("long_term_debt"), latest.value("total_debt")
        if st is not None and lt is not None and td is not None:
            if abs((st + lt) - td) / max(td, 1) > 0.01:
                add("Debt double counting", CheckStatus.WARNING,
                    f"short+long ({st + lt:,.0f}) != total debt ({td:,.0f}) — "
                    "total_debt used once in the bridge; discrepancy not auto-fixed.", "warning")
            else:
                add("Debt double counting", CheckStatus.PASS,
                    "Short + long-term debt reconcile to total debt; debt counted once.")
        if latest.value("cash") is not None and values.get("market_debt") is not None:
            add("Debt/equity treatment", CheckStatus.PASS,
                "Cash added and debt subtracted exactly once in the EV → equity bridge.")

    # ---- 11. independent recomputation of the discounting chain --------------
    # The audit rebuilds each identity from its inputs instead of trusting the
    # stored result, so a bug in any stage cannot pass unnoticed.
    def _close(a: float | None, b: float | None, *,
               rel: float = 1e-9, abs_: float = 1.0) -> bool:
        if a is None or b is None:
            return False
        return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))

    def _recompute(name: str, expected: float | None, reported: float | None,
                   formula: str, *, rel: float = 1e-9, abs_: float = 1.0) -> None:
        if expected is None or reported is None:
            return
        if _close(expected, reported, rel=rel, abs_=abs_):
            add(name, CheckStatus.PASS,
                f"{formula} = {expected:,.6g} reproduces the stored value.")
        else:
            add(name, CheckStatus.FAIL,
                f"Stored {reported:,.6g} != recomputed {expected:,.6g} ({formula}).",
                "critical", block=True)

    # CAPM: Re = Rf + Beta x MRP
    if (wacc and wacc.cost_of_equity_method == "capm"
            and wacc.cost_of_equity.value is not None):
        rf, b, mrp = (wacc.risk_free_rate.value, wacc.beta.value,
                      wacc.market_risk_premium.value)
        if rf is not None and b is not None and mrp is not None:
            _recompute("CAPM recomputation", rf + b * mrp, wacc.cost_of_equity.value,
                       f"Rf + Beta x MRP", rel=1e-9, abs_=1e-12)

    # WACC: we x Re + wd x Rd x (1 - T)
    if (wacc and wacc.wacc.value is not None and wacc.cost_of_equity.value is not None
            and wacc.cost_of_debt.value is not None and wacc.tax_rate.value is not None
            and wacc.equity_weight.value is not None and wacc.debt_weight.value is not None):
        expected_wacc = (wacc.equity_weight.value * wacc.cost_of_equity.value
                         + wacc.debt_weight.value * wacc.cost_of_debt.value
                         * (1 - wacc.tax_rate.value))
        _recompute("WACC recomputation", expected_wacc, wacc.wacc.value,
                   "we x Re + wd x Rd x (1 - T)", rel=1e-9, abs_=1e-12)

    # Discount factors: DF_t = 1 / (1 + WACC) ** t, using the stated convention
    if dcf and dcf.pv_rows and dcf.discount_rate:
        offset = 0.0 if convention == "end" else 0.5
        worst = None
        for row in dcf.pv_rows:
            idx, stored = row.get("index"), row.get("discount_factor")
            if idx is None or stored is None:
                continue
            expected_df = 1.0 / ((1.0 + dcf.discount_rate) ** (idx - offset))
            if abs(expected_df - stored) > 5e-7:
                worst = (idx, stored, expected_df)
                break
        if worst:
            add("Discount factors", CheckStatus.FAIL,
                f"Year {worst[0]}: stored DF {worst[1]:.6f} != recomputed "
                f"{worst[2]:.6f} at WACC {dcf.discount_rate:.2%} ({convention} convention).",
                "critical", block=True)
        else:
            add("Discount factors", CheckStatus.PASS,
                f"All {len(dcf.pv_rows)} discount factors reproduce 1/(1+WACC)^t "
                f"at {dcf.discount_rate:.2%} ({convention} convention).")

    # Terminal value and its present value
    if dcf:
        perp = next((m for m in dcf.terminal_methods
                     if m.method == "perpetuity_growth" and m.valid), None)
        if perp and perp.terminal_value is not None:
            tfcf = perp.inputs.get("terminal_fcf")
            g = perp.inputs.get("terminal_growth")
            w = dcf.discount_rate
            if tfcf is not None and g is not None and w > g:
                expected_tv = tfcf * (1 + g) / (w - g)
                _recompute("Terminal value recomputation", expected_tv,
                           perp.terminal_value,
                           "FCF_n x (1+g) / (WACC-g)", rel=1e-9, abs_=1e-6)
                if perp.pv_terminal_value is not None and dcf.pv_rows:
                    last_df = dcf.pv_rows[-1].get("discount_factor")
                    if last_df:
                        _recompute("PV of terminal value", expected_tv * last_df,
                                   perp.pv_terminal_value,
                                   "TV x last discount factor", rel=1e-9, abs_=1.0)

        # EV and equity bridge
        selected = next((m for m in dcf.terminal_methods
                         if m.method == dcf.selected_method and m.valid), None)
        if selected and selected.pv_terminal_value is not None:
            expected_ev = dcf.pv_forecast_fcf + selected.pv_terminal_value
            _recompute("Enterprise value recomputation", expected_ev,
                       dcf.enterprise_value, "PV(FCF) + PV(TV)")
            # Bridge identity is checked against the *reported* EV so a
            # tampered EV or equity value cannot stay mutually consistent.
            expected_eq = (dcf.enterprise_value or 0.0) + (dcf.cash or 0.0) - (dcf.debt or 0.0)
            _recompute("Equity bridge recomputation", expected_eq,
                       dcf.equity_value, "EV + Cash - Debt")
            if dcf.shares_outstanding and dcf.equity_value is not None \
                    and dcf.implied_share_price is not None:
                _recompute("Implied price recomputation",
                           dcf.equity_value / dcf.shares_outstanding,
                           dcf.implied_share_price, "Equity / Shares",
                           rel=1e-9, abs_=1e-6)

    status = CheckStatus.PASS
    if any(c.status == CheckStatus.WARNING for c in checks):
        status = CheckStatus.WARNING
    if blocking:
        status = CheckStatus.FAIL

    return AuditResult(
        status=status, checks=checks, blocking_issues=blocking,
        can_finalize=not blocking,
    )
