"""Report stage — research-style valuation report with typed sections.

Section kinds make provenance explicit: FACT / CALCULATION / ASSUMPTION /
USER OVERRIDE / MODEL ESTIMATE / NARRATIVE / WARNING.
Deterministic by default; an optional LLM may draft narrative paragraphs only,
and every number in the report comes from computed artifacts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.llm import llm_complete
from ..schemas.common import AuditResult, Assumption, CheckStatus
from ..schemas.company import CompanyInfo, PeriodData
from ..schemas.valuation import (
    ComparablesResult, FcfSchedule, ForecastResult, HistoricalAnalysis,
    ReportDoc, ReportSection, SensitivityResult, ScenarioComparison,
    WaccCalculation, DcfResult,
)

KIND_LABEL = {
    "FACT": "FACT", "CALCULATION": "CALCULATION", "ASSUMPTION": "ASSUMPTION",
    "USER OVERRIDE": "USER OVERRIDE", "MODEL ESTIMATE": "MODEL ESTIMATE",
    "NARRATIVE": "NARRATIVE", "WARNING": "WARNING",
}


def _money(x: float | None, cur: str = "") -> str:
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    return f"{sign}{cur}{abs(x):,.0f}"


def _pct(x: float | None) -> str:
    return f"{x:.2%}" if x is not None else "n/a"


def _table(columns: list[str], rows: list[list]) -> dict:
    return {"columns": columns, "rows": rows}


def build_report(
    company: CompanyInfo,
    periods: list[PeriodData],
    historical: HistoricalAnalysis | None,
    assumptions: list[Assumption],
    forecast: ForecastResult | None,
    wacc: WaccCalculation | None,
    fcf: FcfSchedule | None,
    dcf: DcfResult | None,
    sensitivity: SensitivityResult | None,
    scenarios: ScenarioComparison | None,
    comparables: ComparablesResult | None,
    audit: AuditResult | None,
    sources: list,
) -> ReportDoc:
    now = datetime.now(timezone.utc)
    cur = company.currency or ""
    sections: list[ReportSection] = []
    llm_used = False

    # 1 — bottom line: verdict vs market, conclusions first ---------------------
    bl: list[str] = []
    price = dcf.implied_share_price if dcf else None
    market = dcf.current_share_price if dcf else None
    upside = dcf.upside_downside if dcf else None
    if price is not None and market:
        if upside is not None and upside <= -0.10:
            bl.append(
                f"OVERVALUED vs our model: the estimated value of {price:,.2f} per share is "
                f"{abs(upside):.1%} BELOW the current market price of {market:,.2f}. "
                f"At today's price the market is paying more than these cash flows justify."
            )
        elif upside is not None and upside >= 0.10:
            bl.append(
                f"UNDERVALUED vs our model: the estimated value of {price:,.2f} per share is "
                f"{upside:.1%} ABOVE the current market price of {market:,.2f}. "
                f"At today's price the market is paying less than these cash flows justify."
            )
        elif upside is not None:
            bl.append(
                f"BROADLY IN LINE: the estimated value of {price:,.2f} per share is within "
                f"±10% of the current market price of {market:,.2f} ({upside:+.1%})."
            )
        else:
            bl.append(
                f"Estimated value {price:,.2f} per share vs market price {market:,.2f}."
            )
    elif price is not None:
        bl.append(
            f"Estimated value: {price:,.2f} per share. Private company — there is no market "
            f"price to compare against."
        )
    else:
        bl.append(
            "Per-share value unavailable (shares outstanding missing) — equity value is still "
            "reported below. No per-share conclusion can be drawn."
        )
    if dcf and dcf.valid:
        bl.append(
            f"Headline numbers: enterprise value {_money(dcf.enterprise_value, cur)}, "
            f"equity value {_money(dcf.equity_value, cur)}, discounted at a WACC of "
            f"{_pct(dcf.discount_rate)} with {_pct(dcf.terminal_growth)} terminal growth."
        )
    if sensitivity and sensitivity.tornado:
        t0 = sensitivity.tornado[0]
        bl.append(
            f"Biggest swing factor: {t0.label} — the value moves from "
            f"{_money(t0.low_result, cur)} to {_money(t0.high_result, cur)} as that input "
            f"varies. Change it on the Assumptions page to test the conclusion."
        )
    if audit:
        bl.append(
            f"Audit: {audit.status.value} — {sum(1 for c in audit.checks if c.status == CheckStatus.PASS)}"
            f" of {len(audit.checks)} checks passed"
            + (f"; {len(audit.blocking_issues)} blocking issue(s)."
               if audit.blocking_issues else "; nothing blocking.")
        )
    bl.append(
        "This is a model estimate, not a price target, and it is highly sensitive to the "
        "assumptions listed below. It is not investment advice."
    )
    bl_rows = [
        ["Estimated value per share",
         f"{price:,.2f}" if price is not None else "unavailable"],
        ["Current market price",
         f"{market:,.2f}" if market else "n/a (private company)"],
        ["Difference",
         f"{upside:+.1%}" if upside is not None else "n/a"],
        ["Enterprise value", _money(dcf.enterprise_value, cur) if dcf else "n/a"],
        ["Equity value", _money(dcf.equity_value, cur) if dcf else "n/a"],
        ["Discount rate (WACC)", _pct(dcf.discount_rate) if dcf else "n/a"],
        ["Terminal growth", _pct(dcf.terminal_growth) if dcf else "n/a"],
        ["Audit status",
         audit.status.value if audit else "n/a"],
    ]
    sections.append(ReportSection(
        heading="1. Bottom Line — Is the Company Valued Properly?",
        kind="CALCULATION", body="\n".join(bl),
        table=_table(["Metric", "Value"], bl_rows),
    ))

    # 2 — risks (conclusions second, before the detail) --------------------------
    risks: list[str] = []
    if dcf and dcf.terminal_methods:
        perp0 = next((m for m in dcf.terminal_methods if m.method == "perpetuity_growth"), None)
        if perp0 and perp0.valid and perp0.pv_terminal_value and dcf.enterprise_value:
            share = perp0.pv_terminal_value / dcf.enterprise_value
            if share > 0.70:
                risks.append(f"Terminal value is {share:.0%} of EV — the valuation is dominated "
                             "by long-run assumptions.")
    if wacc and wacc.warnings:
        risks.extend(wacc.warnings)
    if fcf and any((y.fcf.value or 0) < 0 for y in fcf.years):
        risks.append("Forecast contains negative FCF years.")
    if any(a.status.value == "Missing" for a in assumptions):
        missing = [a.label for a in assumptions if a.status.value == "Missing"]
        risks.append("Missing inputs: " + ", ".join(missing))
    if company.is_public is False:
        risks.append("Private company: no observable market price/beta; estimates rely on comparables.")
    if audit and audit.status == CheckStatus.WARNING:
        risks.append(f"Audit raised {sum(1 for c in audit.checks if c.status.value == 'WARNING')} "
                     "warning(s) — review the Audit section.")
    if not risks:
        risks.append("No material model risks detected beyond standard model sensitivity.")
    sections.append(ReportSection(heading="2. Key Risks", kind="WARNING",
                                  body="\n- ".join([""] + risks)))

    # 3 — overview -------------------------------------------------------------
    overview_lines = [
        f"{company.name}" + (f" ({company.ticker})" if company.ticker else " (private company)"),
        f"Industry: {company.industry or 'not classified'} | Currency: {cur} | "
        f"Provider: {company.provider or 'n/a'}",
        f"Data retrieved: {company.retrieved_at.isoformat() if company.retrieved_at else 'n/a'}",
        f"Annual periods analysed: {', '.join(p.period for p in periods) or 'none'}",
    ]
    narrative = ""
    if company.ticker and company.industry:
        narrative, used = llm_complete(
            "You are a sell-side research analyst. Write 2-3 factual sentences about the "
            "company based ONLY on the provided facts. No investment advice, no price targets.",
            f"Company: {company.name}, ticker {company.ticker}, industry {company.industry}, "
            f"latest revenue {_money(periods[-1].value('revenue') if periods else None, cur)}.",
        )
        llm_used = llm_used or used
    sections.append(ReportSection(
        heading="3. Company Overview",
        kind="NARRATIVE" if narrative else "FACT",
        body="\n".join(overview_lines) + ("\n\n" + narrative if narrative else ""),
    ))

    # 2 — historical -----------------------------------------------------------
    rows = []
    if historical:
        for r in historical.rows:
            rows.append([r.period] + [
                _pct(r.values[k].value) if k in r.values else "n/a"
                for k in ("revenue_growth", "gross_margin", "ebit_margin",
                          "ebitda_margin", "effective_tax_rate", "capex_pct", "fcf_margin")
            ])
    hist_table = _table(
        ["Period", "Rev growth", "Gross margin", "EBIT margin", "EBITDA margin",
         "Effective tax", "CapEx/Rev", "FCF margin"], rows)
    facts = historical.facts if historical else ["No historical analysis available."]
    interp = historical.interpretation if historical else []
    body = ("FACTS (computed from reported numbers):\n- " + "\n- ".join(facts) +
            ("\n\nINTERPRETATION (qualitative, not a fact):\n- " + "\n- ".join(interp)
             if interp else ""))
    sections.append(ReportSection(heading="4. Historical Financial Performance",
                                  kind="FACT", body=body, table=hist_table))

    # 3 — assumptions ----------------------------------------------------------
    arows = []
    for a in assumptions:
        arows.append([
            a.label,
            _pct(a.value) if a.unit.value == "percent" else (
                f"{a.value:,.2f}" if a.value is not None else "n/a"),
            _pct(a.historical_value) if a.unit.value == "percent" else a.historical_value,
            _pct(a.model_estimate) if a.unit.value == "percent" else a.model_estimate,
            _pct(a.user_value) if a.unit.value == "percent" else a.user_value,
            a.source_type.value,
        ])
    overrides = [a for a in assumptions if a.is_override]
    sections.append(ReportSection(
        heading="5. Forecast Assumptions & Overrides",
        kind="USER OVERRIDE" if overrides else "ASSUMPTION",
        body=("User overrides applied to: " + ", ".join(a.label for a in overrides)
              + "\n" if overrides else "All inputs are model estimates or retrieved data.\n") +
             "Precedence: USER OVERRIDE > user data > model estimate.",
        table=_table(["Input", "Final used", "Historical", "Model estimate",
                      "User override", "Source type"], arows),
    ))

    # 4 — WACC -----------------------------------------------------------------
    if wacc:
        body = (
            f"CAPM: {wacc.capm_formula}\n"
            f"WACC: {wacc.wacc_formula}\n"
            f"Result: WACC = {_pct(wacc.wacc.value)}\n\n"
            f"Market value of equity: {_money(wacc.market_value_equity.value, cur)}\n"
            f"Market value of debt:   {_money(wacc.market_value_debt.value, cur)}\n"
            f"Weights: E {wacc.equity_weight.value:.2%} / D {wacc.debt_weight.value:.2%}\n"
            f"Beta ({wacc.beta_method}): {wacc.beta.value:.3f}\n"
            f"Cost of debt ({wacc.cost_of_debt_method}): {_pct(wacc.cost_of_debt.value)}\n"
            f"Tax rate ({wacc.tax_rate_method}): {_pct(wacc.tax_rate.value)}\n"
            + ("\nWarnings:\n- " + "\n- ".join(wacc.warnings) if wacc.warnings else "")
        )
        sections.append(ReportSection(heading="6. WACC", kind="CALCULATION", body=body))

    # 5 — FCF ------------------------------------------------------------------
    if fcf:
        rows = [[y.period, _money(y.ebit.value), _pct(y.tax_rate.value),
                 _money(y.tax_expense.value), _money(y.nopat.value), _money(y.da.value),
                 _money(y.capex.value), _money(y.change_nwc.value), _money(y.fcf.value),
                 y.discount_factor, _money(y.pv_fcf)] for y in fcf.years]
        sections.append(ReportSection(
            heading="7. Free Cash Flow Forecast", kind="CALCULATION",
            body="UFCF = EBIT x (1 − T) + D&A − CapEx − ΔNWC (each year shown component-by-component).",
            table=_table(["Period", "EBIT", "Tax rate", "Tax", "NOPAT", "D&A", "CapEx",
                          "ΔNWC", "FCF", "DF", "PV(FCF)"], rows),
        ))

    # 6 — DCF -------------------------------------------------------------------
    if dcf:
        rows = [[r["period"], _money(r["fcf"]), f"{r['discount_factor']:.4f}",
                 _money(r["pv"])] for r in dcf.pv_rows]
        bridge = "\n".join(f"  {b['label']}: {_money(b['value'])}  ({b['detail']})"
                           for b in dcf.bridge) if dcf.bridge else "n/a"
        tm = "\n".join(
            f"  [{m.label}] {'VALID' if m.valid else 'BLOCKED'}: {m.formula}"
            + (f" -> EV {_money(m.ev)}, price {m.implied_share_price:,.2f}"
               if m.valid and m.implied_share_price else "")
            + (f"  ISSUE: {m.issue}" if m.issue else "")
            for m in dcf.terminal_methods)
        body = (f"PV of forecast FCF: {_money(dcf.pv_forecast_fcf)}\n"
                f"Terminal value methods:\n{tm}\n\nEquity bridge:\n{bridge}\n\n")
        if dcf.implied_share_price is not None:
            body += f"Implied share price: {dcf.implied_share_price:,.2f}"
        else:
            body += "Implied share price: unavailable (shares outstanding missing)"
        if dcf.issue:
            body += f"\n\nWARNING: {dcf.issue}"
        sections.append(ReportSection(
            heading="8. DCF Valuation & Terminal Value",
            kind="WARNING" if dcf.issue else "CALCULATION", body=body,
            table=_table(["Period", "FCF", "Discount factor", "PV"], rows),
        ))

    # 7 — sensitivity -----------------------------------------------------------
    if sensitivity and sensitivity.tables:
        lines = []
        for t in sensitivity.tables:
            defined = [v for row in t.matrix for v in row if v is not None]
            if defined:
                lines.append(f"{t.title}: range {_money(min(defined))} – {_money(max(defined))} "
                             f"(base {_money(t.base_value)})")
        for item in sensitivity.tornado[:5]:
            lines.append(f"Swing — {item.label}: {_money(item.low_result)} to {_money(item.high_result)}")
        lines.append("Conditional ranges, not predictions.")
        sections.append(ReportSection(heading="9. Sensitivity Analysis",
                                      kind="CALCULATION", body="\n".join(lines)))

    # 8 — scenarios ---------------------------------------------------------------
    if scenarios and scenarios.scenarios:
        rows = [[s.label, _pct(s.wacc), _pct(s.terminal_growth), _money(s.enterprise_value),
                 _money(s.equity_value),
                 f"{s.implied_share_price:,.2f}" if s.implied_share_price else "n/a",
                 "OK" if s.valid else (s.issue or "blocked")]
                for s in scenarios.scenarios]
        sections.append(ReportSection(
            heading="10. Scenario Analysis", kind="CALCULATION",
            body=f"Active scenario: {scenarios.active}.",
            table=_table(["Scenario", "WACC", "Terminal g", "EV", "Equity", "Price", "Status"], rows),
        ))

    # 9 — comparables ---------------------------------------------------------------
    if comparables and comparables.status == "ok":
        rows = [[m, f"{s['median']:,.2f}x" if s["median"] else "n/a", s["count"]]
                for m, s in comparables.multiple_stats.items()]
        irows = [[r["multiple"], f"{r['peer_median']:,.2f}", _money(r["implied_ev"]),
                  _money(r["implied_equity"]),
                  f"{r['implied_price']:,.2f}" if r["implied_price"] else "n/a"]
                 for r in comparables.implied_values]
        body = "\n".join(comparables.notes)
        sections.append(ReportSection(
            heading="11. Comparable Valuation", kind="FACT", body=body + "\n\nImplied values:",
            table=(_table(["Multiple", "Median", "Implied EV", "Implied equity", "Implied price"], irows)
                   if irows else _table(["Multiple", "Peer median", "Count"], rows)),
        ))
    else:
        reason = (comparables.notes[0] if comparables and comparables.notes
                  else "Comparables not run.")
        sections.append(ReportSection(heading="11. Comparable Valuation", kind="WARNING",
                                      body=reason))

    # key assumptions ----------------------------------------------------------------
    key_assumptions = [a for a in assumptions if a.group in ("forecast", "terminal", "wacc")
                       and a.value is not None]
    lines = [f"{a.label}: {_pct(a.value) if a.unit.value == 'percent' else a.value} "
             f"[{a.source_type.value} — {a.source}]" for a in key_assumptions]
    sections.append(ReportSection(heading="12. Key Assumptions", kind="ASSUMPTION",
                                  body="\n".join(lines)))

    # 12 — data sources ----------------------------------------------------------------
    slines = []
    for s in sources:
        slines.append(f"- {s.name} [{s.source_type.value}]"
                      + (f" — {s.url}" if s.url else "")
                      + (f" (retrieved {s.retrieved_at})" if s.retrieved_at else ""))
    sections.append(ReportSection(heading="13. Data Sources", kind="FACT",
                                  body="\n".join(slines) or "No sources recorded."))

    # 13 — audit status -----------------------------------------------------------------
    if audit:
        lines = [f"Overall: {audit.status.value} ({'finalizable' if audit.can_finalize else 'BLOCKED'})"]
        for c in audit.checks:
            lines.append(f"[{c.status.value}] {c.name}: {c.detail}")
        if audit.blocking_issues:
            lines.append("\nBLOCKING:\n- " + "\n- ".join(audit.blocking_issues))
        sections.append(ReportSection(heading="14. Audit Status",
                                      kind="WARNING" if audit.blocking_issues else "CALCULATION",
                                      body="\n".join(lines)))

    doc = ReportDoc(
        title=f"Valuation Report — {company.name}",
        subtitle=(f"{company.ticker} | {now.date().isoformat()}" if company.ticker
                  else f"Private company | {now.date().isoformat()}"),
        generated_at=now,
        sections=sections,
        audit_status=(audit.status if audit else CheckStatus.PASS),
        llm_used=llm_used,
    )
    doc.markdown = to_markdown(doc)
    return doc


def to_markdown(doc: ReportDoc) -> str:
    lines = [f"# {doc.title}", f"*{doc.subtitle}*", "",
             f"> **Disclaimer:** {doc.disclaimer}", ""]
    for s in doc.sections:
        lines.append(f"## {s.heading}  `[{KIND_LABEL.get(s.kind, s.kind)}]`")
        if s.body:
            lines.append(s.body)
        if s.table and s.table.get("rows") is not None:
            cols = s.table["columns"]
            lines.append("")
            lines.append("| " + " | ".join(str(c) for c in cols) + " |")
            lines.append("|" + "|".join([" --- "] * len(cols)) + "|")
            for row in s.table["rows"]:
                lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
        lines.append("")
    return "\n".join(lines)
