"""WACC stage — assembles the full calculation with transparent formulas.

Supports:
  cost of equity : CAPM | manual expected return
  beta           : market (regression) | comparables (Hamada) | manual
  cost of debt   : interest-bearing capacity | debt instruments | manual
  tax rate       : historical effective | statutory | manual
  structure      : current | target D/E | manual weights
"""
from __future__ import annotations

from ..core.errors import MissingDataError, ValidationError
from ..schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from ..schemas.company import PeriodData
from ..schemas.valuation import BetaDetail, WaccCalculation
from ..valuation import (
    calculate_after_tax_cost_of_debt,
    calculate_capm,
    calculate_capital_weights,
    calculate_cost_of_debt,
    calculate_wacc,
    comparable_beta_estimate,
    wacc_formula,
)

DEFAULT_MRP = 0.05


def _sv(value: float | None, unit: Unit, source: str, status: ValueStatus,
        stype: SourceType, note: str | None = None) -> SourcedValue:
    return SourcedValue(value=value, unit=unit, source=source, status=status,
                        source_type=stype, note=note)


def build_wacc(
    values: dict[str, float | None],
    options,
    periods: list[PeriodData],
    *,
    debt_instruments: list[dict] | None = None,
    peers: list | None = None,  # list[PeerMetrics] with levered_beta
    private: bool = False,
) -> WaccCalculation:
    warnings: list[str] = []
    beta_details: list[BetaDetail] = []

    # ---- tax rate -----------------------------------------------------------
    tax = values.get("tax_rate")
    if tax is None:
        raise MissingDataError("Tax rate is required for WACC.")
    tax_method = options.tax_rate_method

    # ---- beta ---------------------------------------------------------------
    beta_method = options.beta_method
    beta: float | None = None
    beta_note = None
    if beta_method == "comparables":
        usable = [p for p in (peers or []) if p.levered_beta]
        if not usable:
            raise MissingDataError(
                "No comparable companies with observable betas.",
                hint="Add peer tickers on the Comparables page, or switch Beta Method to market/manual."
            )
        peer_inputs = []
        for p in usable:
            net_debt = (p.ev - p.market_cap) if (p.ev is not None and p.market_cap) else 0.0
            de = (net_debt / p.market_cap) if p.market_cap else 0.0
            peer_inputs.append((p.ticker, p.levered_beta, max(de, 0.0), tax))
        target_de = values.get("target_de") or 0.0
        est = comparable_beta_estimate(peer_inputs, target_de, tax,
                                       method=options.beta_aggregation)
        beta = est.relevered_beta
        beta_note = "; ".join(est.formula_lines)
        for ticker, bu in est.unlevered_betas:
            peer = next((p for p in usable if p.ticker == ticker), None)
            beta_details.append(BetaDetail(
                ticker=ticker, name=peer.name if peer else None,
                levered_beta=peer.levered_beta if peer else None,
                tax_rate=tax, debt_equity=next(
                    (r[2] for r in peer_inputs if r[0] == ticker), None),
                unlevered_beta=bu, selected=True,
                note="unlevered at peer D/E, aggregated, relevered at target D/E",
            ))
        warnings.append(
            f"Beta from {len(usable)} comparables ({options.beta_aggregation} unlevered, "
            f"relevered at D/E {target_de:.2f})."
        )
    else:
        beta = values.get("beta")
        if beta is None:
            raise MissingDataError(
                "Beta is unavailable and no beta method produced a value.",
                hint="Set Beta Method to 'Manual Beta' and enter a value, or add comparable companies.",
            )
        beta_note = ("Market regression vs SPY" if beta_method == "market"
                     else "Manual beta supplied by the user")
        beta_details.append(BetaDetail(
            ticker=None, levered_beta=beta, tax_rate=tax,
            debt_equity=values.get("target_de") or 0.0, unlevered_beta=None,
            selected=True, note=beta_note,
        ))

    # ---- cost of equity -----------------------------------------------------
    cost_of_equity: float | None = None
    capm_formula = ""
    if options.cost_of_equity_method == "capm":
        rf = values.get("risk_free_rate")
        mrp = values.get("market_risk_premium", DEFAULT_MRP)
        if rf is None:
            raise MissingDataError("Risk-free rate is required for CAPM.")
        capm = calculate_capm(rf, beta, mrp)
        cost_of_equity = capm.cost_of_equity
        capm_formula = capm.formula
    else:
        cost_of_equity = values.get("cost_of_equity")
        if cost_of_equity is None:
            raise MissingDataError(
                "Manual expected cost of equity not provided.",
                hint="Enter 'Cost of Equity' on the Assumptions page (decimal, e.g. 0.12).",
            )
        capm = calculate_capm(values.get("risk_free_rate") or 0.0, beta,
                              values.get("market_risk_premium", DEFAULT_MRP))
        capm_formula = (f"CAPM reference = {capm.cost_of_equity:.2%}; "
                        f"USER OVERRIDE in use = {cost_of_equity:.2%}")
        warnings.append("Cost of equity uses a manual expected return, not CAPM (user choice).")

    # ---- cost of debt -------------------------------------------------------
    rd_method = options.cost_of_debt_method
    instruments_payload: list[dict] = []
    if rd_method == "instruments" and debt_instruments:
        pairs = [(d["amount"], d["rate"]) for d in debt_instruments]
        rd = calculate_cost_of_debt(debt_instruments=pairs)
        instruments_payload = list(debt_instruments)
        rd_note = "Weighted average of user-provided debt instruments."
    elif rd_method == "instruments" and not debt_instruments:
        warnings.append("Debt Instrument method selected but no instruments provided — "
                        "falling back to interest-bearing capacity estimate.")
        rd = values.get("cost_of_debt")
        rd_note = "Fallback: interest expense / total debt."
        if rd is None:
            raise MissingDataError("Cost of debt could not be determined.")
    else:  # interest_bearing or manual
        rd = values.get("cost_of_debt")
        rd_note = ("Manual cost of debt (user)."
                   if rd_method == "manual" and values.get("cost_of_debt") is not None
                   else "Interest expense / total debt from reported statements.")
        if rd is None:
            raise MissingDataError("Cost of debt could not be determined.")

    after_tax_rd = calculate_after_tax_cost_of_debt(rd, tax)

    # ---- capital structure --------------------------------------------------
    cs_method = options.capital_structure_method
    me, md = values.get("market_equity"), values.get("market_debt")
    if cs_method == "current":
        if not me or me <= 0:
            raise MissingDataError(
                "Market value of equity is unavailable, so current weights cannot be computed.",
                hint="Private company? Enter an Estimated Equity Value on the Assumptions page, "
                     "or switch Capital Structure to 'Target D/E'.",
            )
        weights = calculate_capital_weights(me, md or 0.0)
    elif cs_method == "target":
        de = values.get("target_de")
        if de is None or de < 0:
            raise MissingDataError("Target D/E is required for target capital structure.")
        wd = de / (1 + de)
        weights = calculate_capital_weights(1.0 - wd, wd)
        weights = weights.__class__(
            equity_weight=1 - wd, debt_weight=wd,
            market_value_equity=me or 0.0, market_value_debt=md or 0.0,
            formula=f"Target D/E = {de:.2f} -> w_d = {wd:.2%}, w_e = {1 - wd:.2%}",
        )
    else:  # manual
        we, wd = values.get("equity_weight"), values.get("debt_weight")
        if we is None or wd is None:
            raise MissingDataError("Manual equity/debt weights are required.")
        weights = calculate_capital_weights(we, wd)  # validates sum == 1

    wacc = calculate_wacc(weights.equity_weight, weights.debt_weight,
                          cost_of_equity, rd, tax)

    if md and me and cs_method == "current":
        warnings.append("Debt weight uses book value of debt as a proxy for market value.")
    if wacc <= (values.get("terminal_growth") or 0.0):
        warnings.append(
            f"WACC ({wacc:.2%}) is not above terminal growth "
            f"({(values.get('terminal_growth') or 0):.2%}) — terminal value will be blocked."
        )

    return WaccCalculation(
        market_value_equity=_sv(me, Unit.CURRENCY,
                                "Market capitalisation" if me else "missing",
                                ValueStatus.CALCULATED if me else ValueStatus.MISSING,
                                SourceType.MODEL_CALCULATION),
        market_value_debt=_sv(md, Unit.CURRENCY, "Total debt (latest balance sheet)",
                              ValueStatus.CALCULATED if md else ValueStatus.ESTIMATED,
                              SourceType.MODEL_CALCULATION,
                              "Book value proxy for market value of debt"),
        equity_weight=_sv(weights.equity_weight, Unit.RATIO, "Capital weights",
                          ValueStatus.CALCULATED, SourceType.MODEL_CALCULATION,
                          weights.formula),
        debt_weight=_sv(weights.debt_weight, Unit.RATIO, "Capital weights",
                        ValueStatus.CALCULATED, SourceType.MODEL_CALCULATION, weights.formula),
        risk_free_rate=_sv(values.get("risk_free_rate"), Unit.PERCENT,
                           "FRED DGS10 / user", ValueStatus.RETRIEVED, SourceType.PUBLIC_API),
        beta=_sv(beta, Unit.RATIO, beta_note or "beta", ValueStatus.CALCULATED
                 if beta_method == "comparables" else ValueStatus.RETRIEVED,
                 SourceType.MODEL_CALCULATION if beta_method == "comparables" else SourceType.PUBLIC_API,
                 beta_note),
        market_risk_premium=_sv(values.get("market_risk_premium", DEFAULT_MRP), Unit.PERCENT,
                                "Model default / user", ValueStatus.ESTIMATED,
                                SourceType.MODEL_ASSUMPTION),
        cost_of_equity=_sv(cost_of_equity, Unit.PERCENT, "CAPM" if
                           options.cost_of_equity_method == "capm" else "Manual expected return",
                           ValueStatus.CALCULATED, SourceType.MODEL_CALCULATION, capm_formula),
        cost_of_debt=_sv(rd, Unit.PERCENT, rd_note, ValueStatus.CALCULATED,
                         SourceType.MODEL_CALCULATION, rd_note),
        after_tax_cost_of_debt=_sv(after_tax_rd, Unit.PERCENT, "Rd x (1 - T)",
                                   ValueStatus.CALCULATED, SourceType.MODEL_CALCULATION),
        tax_rate=_sv(tax, Unit.PERCENT, f"method: {tax_method}", ValueStatus.ESTIMATED,
                     SourceType.MODEL_ASSUMPTION),
        wacc=_sv(wacc, Unit.PERCENT, "WACC formula", ValueStatus.CALCULATED,
                 SourceType.MODEL_CALCULATION),
        capm_formula=capm_formula,
        wacc_formula=wacc_formula(weights.equity_weight, cost_of_equity,
                                  weights.debt_weight, rd, tax),
        cost_of_equity_method=options.cost_of_equity_method,
        beta_method=beta_method,
        cost_of_debt_method=rd_method,
        tax_rate_method=tax_method,
        capital_structure_method=cs_method,
        beta_details=beta_details,
        debt_instruments=instruments_payload,
        warnings=warnings,
    )
