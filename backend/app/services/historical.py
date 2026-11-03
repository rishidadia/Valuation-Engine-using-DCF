"""Historical analysis stage.

Computes ratios and trends from raw periods, and strictly separates:
  FACTS          — arithmetic on reported numbers
  INTERPRETATION — qualitative reading of the facts
  ASSUMPTIONS    — proposed forward drivers (user can override each)
"""
from __future__ import annotations

import statistics
from typing import Sequence

from ..schemas.common import Assumption, SourceType, SourcedValue, Unit, ValueStatus
from ..schemas.company import PeriodData
from ..schemas.valuation import HistoricalAnalysis, RatioRow

TAX_RATE_FLOOR, TAX_RATE_CEIL = 0.0, 0.50


def _cost(v: float | None) -> float | None:
    """Cost lines are stored as positive outflows regardless of input sign."""
    return abs(v) if v is not None else None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def _sv(value: float | None, *, unit: Unit, note: str | None = None,
        status: ValueStatus = ValueStatus.CALCULATED) -> SourcedValue:
    return SourcedValue(
        value=value, unit=unit, source_type=SourceType.MODEL_CALCULATION,
        source="Historical analysis (calculated)", status=status, note=note,
    )


def normalize_signs(periods: list[PeriodData]) -> list[str]:
    """Enforce canonical signs: costs/outflows positive.

    Returns warnings describing any flip (never silent).
    """
    warnings: list[str] = []
    cost_keys = {"cogs", "operating_expenses", "interest_expense",
                 "income_tax_expense", "capex"}
    for p in periods:
        for key in cost_keys:
            sv = p.metrics.get(key)
            if sv is None or sv.value is None or sv.value >= 0:
                continue
            sv.note = (f"{sv.note + ' | ' if sv.note else ''}"
                       f"sign normalised: reported {sv.value:,.0f}, stored as positive outflow")
            sv.original_value = sv.original_value if sv.original_value is not None else sv.value
            sv.value = abs(sv.value)
            warnings.append(
                f"{p.period}: '{key}' reported as negative; stored as a positive outflow "
                "so downstream formulas stay consistent."
            )
    return warnings


def nwc_of(p: PeriodData) -> float | None:
    """Net working capital = AR + Inventory - AP (balance sheet)."""
    ar = p.value("accounts_receivable")
    inv = p.value("inventory")
    ap = p.value("accounts_payable")
    if ar is None and inv is None and ap is None:
        return None
    return (ar or 0.0) + (inv or 0.0) - (ap or 0.0)


def change_nwc_history(periods: list[PeriodData]) -> dict[str, float]:
    """Year-over-year change in NWC where balance-sheet data allows."""
    out: dict[str, float] = {}
    for prev, cur in zip(periods, periods[1:]):
        n0, n1 = nwc_of(prev), nwc_of(cur)
        if n0 is not None and n1 is not None:
            out[cur.period] = n1 - n0
    return out


def analyze(periods: list[PeriodData], *, private: bool = False) -> HistoricalAnalysis:
    if not periods:
        return HistoricalAnalysis(interpretation=["No historical periods available for analysis."])

    dnwc = change_nwc_history(periods)
    rows: list[RatioRow] = []
    prev: PeriodData | None = None
    period_series: list[dict[str, float | None]] = []

    for p in periods:
        vals: dict[str, SourcedValue] = {}
        rev = p.value("revenue")
        cogs = _cost(p.value("cogs"))
        gp = p.value("gross_profit")
        ebit = p.value("ebit")
        da = p.value("da") if p.value("da") is not None else p.value("da_cf")
        ebt = p.value("ebt")
        tax = _cost(p.value("income_tax_expense"))
        ni = p.value("net_income")
        capex = _cost(p.value("capex"))
        ocf = p.value("operating_cash_flow")
        ebitda = p.value("ebitda")

        ebit_note: str | None = None
        if ebit is None and ebt is not None and rev is not None:
            # Belt-and-braces (mirrors the provider derivation): some filers
            # never tag operating income — reconstruct EBIT from pre-tax income
            # so the ebit_margin driver stays derivable. Interest added back
            # unless it exceeds 20% of revenue (revenue then reported net of
            # interest). Labelled on the ratio row — never silent.
            intr = _cost(p.value("interest_expense"))
            if intr is not None and abs(intr) / abs(rev) > 0.20:
                ebit = ebt
                ebit_note = "EBIT ≈ EBT — revenue reported net of interest expense"
            elif intr is not None:
                ebit = ebt + intr
                ebit_note = "EBIT ≈ EBT + interest expense (operating income not reported)"
            else:
                ebit = ebt
                ebit_note = "EBIT ≈ EBT (operating income not reported)"

        growth = None
        if prev is not None and rev is not None and prev.value("revenue"):
            growth = rev / prev.value("revenue") - 1.0
        gp_margin = _ratio(gp if gp is not None else (
            rev - cogs if rev is not None and cogs is not None else None), rev)
        ebit_margin = _ratio(ebit, rev)
        ebitda_calc = ebitda if ebitda is not None else (
            ebit + da if ebit is not None and da is not None else None)
        ebitda_margin = _ratio(ebitda_calc, rev)
        tax_rate = (tax / ebt) if (tax is not None and ebt and ebt > 0
                                   and TAX_RATE_FLOOR <= tax / ebt <= TAX_RATE_CEIL) else None
        da_pct = _ratio(da, rev)
        capex_pct = _ratio(capex, rev)
        change = dnwc.get(p.period)
        nwc = nwc_of(p)
        nwc_pct = _ratio(nwc, rev)
        if change is not None and rev is not None:
            fcf = (ebit * (1 - (tax_rate if tax_rate is not None else 0.0))
                   if ebit is not None else None)
            if fcf is not None:
                fcf = fcf + (da or 0.0) - (capex or 0.0) - change
        elif ocf is not None and capex is not None:
            fcf = ocf - capex  # fallback measure, labelled below
        else:
            fcf = None
        fcf_margin = _ratio(fcf, rev)
        net_margin = _ratio(ni, rev)

        metrics = {
            "revenue_growth": growth, "gross_margin": gp_margin, "ebit_margin": ebit_margin,
            "ebitda_margin": ebitda_margin, "net_margin": net_margin,
            "effective_tax_rate": tax_rate, "da_pct": da_pct, "capex_pct": capex_pct,
            "nwc_pct": nwc_pct, "fcf_margin": fcf_margin,
        }
        period_series.append(metrics)
        rows.append(RatioRow(
            period=p.period, fiscal_year=p.fiscal_year,
            values={k: _sv(v, unit=Unit.PERCENT if k != "revenue_growth" else Unit.PERCENT,
                           note=(ebit_note if k == "ebit_margin" else None))
                    for k, v in metrics.items() if v is not None}
            | ({"fcf": _sv(fcf, unit=Unit.CURRENCY)} if fcf is not None else {}),
        ))
        prev = p

    # ---- summary statistics ------------------------------------------------
    revs = [p.value("revenue") for p in periods if p.value("revenue")]
    summary: dict[str, SourcedValue] = {}
    facts: list[str] = []
    if len(revs) >= 2 and revs[0] > 0:
        n = len(revs) - 1
        cagr = (revs[-1] / revs[0]) ** (1 / n) - 1
        summary["revenue_cagr"] = _sv(cagr, unit=Unit.PERCENT,
                                      note=f"CAGR over {n} periods ({periods[0].period}–{periods[-1].period})")
        facts.append(
            f"Revenue CAGR of {cagr:.1%} from {periods[0].period} to {periods[-1].period} "
            f"({revs[0]:,.0f} → {revs[-1]:,.0f})."
        )

    def _avg(key: str, last: int | None = None) -> float | None:
        series = [m[key] for m in period_series[-(last or len(period_series)):]]
        clean = [x for x in series if x is not None]
        return statistics.mean(clean) if clean else None

    for key, label in (("ebit_margin", "EBIT margin"), ("ebitda_margin", "EBITDA margin"),
                       ("gross_margin", "Gross margin"), ("effective_tax_rate", "Effective tax rate"),
                       ("da_pct", "D&A / revenue"), ("capex_pct", "CapEx / revenue"),
                       ("nwc_pct", "NWC / revenue"), ("fcf_margin", "FCF margin")):
        avg = _avg(key)
        if avg is not None:
            summary[f"avg_{key}"] = _sv(avg, unit=Unit.PERCENT, note="mean of available periods")

    growths = [m["revenue_growth"] for m in period_series if m["revenue_growth"] is not None]
    if growths:
        summary["median_revenue_growth"] = _sv(statistics.median(growths), unit=Unit.PERCENT,
                                               note=f"median of {len(growths)} YoY observations")
        facts.append(
            f"YoY revenue growth ranged {min(growths):.1%} to {max(growths):.1%} "
            f"(median {statistics.median(growths):.1%})."
        )

    margins = [m["ebit_margin"] for m in period_series if m["ebit_margin"] is not None]
    if len(margins) >= 2:
        delta = margins[-1] - margins[0]
        facts.append(
            f"EBIT margin moved from {margins[0]:.1%} to {margins[-1]:.1%} "
            f"({'expansion' if delta > 0.005 else 'contraction' if delta < -0.005 else 'roughly flat'} "
            f"of {abs(delta):.1%})."
        )

    # ---- interpretation (clearly qualitative) -------------------------------
    interpretation: list[str] = []
    if len(growths) >= 2:
        trend = "decelerating" if growths[-1] < statistics.median(growths) else "above-median"
        interpretation.append(
            f"Recent growth is {trend}: latest {growths[-1]:.1%} vs median {statistics.median(growths):.1%}. "
            "This reading is qualitative; the forecast driver is set separately."
        )
    if margins and len(margins) >= 3 and margins[-1] > margins[0]:
        interpretation.append("Operating margins have trended upward — consider whether that pace is sustainable.")
    if margins and margins[-1] < 0:
        interpretation.append("Latest operating margin is negative; a margin-expansion assumption needs explicit justification.")
    if private:
        interpretation.append(
            "Private company: no observable market beta or price. Comparable-company beta "
            "and manual inputs are required; all such inputs are labelled as estimates."
        )

    # ---- proposed forward assumptions (model estimates) ---------------------
    proposed: list[Assumption] = []

    def prop(key: str, label: str, value: float | None, unit: Unit, note: str,
             group: str = "forecast", hist_key: str | None = None) -> None:
        hk = hist_key or key
        hv = _avg(hk)
        if hv is None and f"avg_{hk}" in summary:
            hv = summary[f"avg_{hk}"].value
        proposed.append(Assumption(
            key=key, label=label, group=group, value=value,
            model_estimate=value, historical_value=hv,
            unit=unit, source_type=SourceType.MODEL_ASSUMPTION,
            source="Historical analysis", status=ValueStatus.ESTIMATED, note=note,
        ))

    growth_est = statistics.median(growths) if growths else None
    if growth_est is not None:
        growth_est = max(min(growth_est, 0.30), -0.15)  # clip extreme history
    prop("revenue_growth", "Revenue Growth", growth_est, Unit.PERCENT,
         "Median historical YoY growth, clipped to [-15%, 30%] for plausibility.")
    prop("ebit_margin", "EBIT Margin", _avg("ebit_margin", 3) or _avg("ebit_margin"), Unit.PERCENT,
         "Mean EBIT margin of the most recent available periods.")
    tax_est = _avg("effective_tax_rate", 3) or _avg("effective_tax_rate")
    prop("tax_rate", "Tax Rate", tax_est, Unit.PERCENT,
         "Mean historical effective tax rate (taxes / EBT).",
         group="wacc", hist_key="effective_tax_rate")
    da_est = _avg("da_pct")
    if da_est is not None:
        da_note = "Mean D&A intensity."
    else:
        # Never let da_pct stay None: an explicit, labelled model assumption
        # keeps the forecast runnable (same pattern as the nwc_pct default).
        capex_proxy = _avg("capex_pct")
        if capex_proxy is not None and capex_proxy > 0:
            da_est = capex_proxy
            da_note = (
                f"NOT DERIVABLE from the provided data — set equal to CapEx intensity "
                f"({capex_proxy:.2%}) as a steady-state proxy (D&A ≈ CapEx). "
                "Provide D&A figures or override this assumption."
            )
        else:
            da_est = 0.0
            da_note = (
                "NOT DERIVABLE from the provided data — default 0% set explicitly. "
                "Provide D&A figures or override this assumption."
            )
    prop("da_pct", "D&A / Revenue", da_est, Unit.PERCENT, da_note)
    capex_est = _avg("capex_pct")
    if capex_est is not None:
        capex_note = "Mean CapEx intensity."
    elif da_est is not None and da_est > 0:
        # Never let capex_pct stay None either: banks (JPM) and service firms
        # often tag no CapEx concept at all — steady-state CapEx ≈ D&A is the
        # standard proxy, explicitly labelled so the user can override.
        capex_est = da_est
        capex_note = (
            f"NOT DERIVABLE from the provided data — set equal to D&A intensity "
            f"({da_est:.2%}) as a steady-state proxy (CapEx ≈ D&A). "
            "Provide CapEx figures or override this assumption."
        )
    else:
        capex_est = 0.0
        capex_note = (
            "NOT DERIVABLE from the provided data — default 0% set explicitly. "
            "Provide CapEx figures or override this assumption."
        )
    prop("capex_pct", "CapEx / Revenue", capex_est, Unit.PERCENT, capex_note)
    nwc_est = _avg("nwc_pct")
    prop("nwc_pct", "NWC / Revenue", nwc_est if nwc_est is not None else 0.0, Unit.PERCENT,
         ("Mean net working capital intensity (AR + Inventory − AP) / Revenue."
          if nwc_est is not None else
          "NOT DERIVABLE from the provided data — default 0% set explicitly. "
          "Provide AR/Inventory/AP or override this assumption."))

    return HistoricalAnalysis(
        periods=[p.period for p in periods], rows=rows, summary=summary,
        facts=facts, interpretation=interpretation, proposed_assumptions=proposed,
    )


def latest_metric_values(periods: Sequence[PeriodData]) -> dict[str, float]:
    if not periods:
        return {}
    latest = periods[-1]
    return {k: sv.value for k, sv in latest.metrics.items() if sv.value is not None}
