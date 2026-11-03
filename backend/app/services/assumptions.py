"""Assumptions & overrides — the heart of transparency.

Precedence for every model input:
    USER OVERRIDE  >  user-provided data (Excel/API input)  >  model estimate
Each Assumption records historical / model / user / final value + provenance.
"""
from __future__ import annotations

import statistics

from ..core.errors import ValidationError
from ..schemas.common import Assumption, SourceType, Unit, ValueStatus
from ..schemas.company import PeriodData
from ..schemas.valuation import HistoricalAnalysis
from ..data.providers.base import MarketSnapshot

# Plausibility bounds — negative growth is fine for a bear case, absurd rates are not.
BOUNDS: dict[str, tuple[float, float]] = {
    "revenue_growth": (-0.50, 1.00),
    "ebit_margin": (-1.00, 1.00),
    "tax_rate": (0.00, 0.75),
    "da_pct": (0.00, 0.50),
    "capex_pct": (0.00, 1.00),
    "nwc_pct": (-0.50, 0.50),
    "risk_free_rate": (-0.02, 0.25),
    "beta": (-1.00, 4.00),
    "market_risk_premium": (0.00, 0.20),
    "cost_of_debt": (0.00, 0.50),
    "cost_of_equity": (0.00, 0.60),
    "terminal_growth": (-0.05, 0.10),
    "exit_multiple": (0.50, 60.00),
    "forecast_years": (1, 15),
    "target_de": (0.00, 5.00),
    "equity_weight": (0.0, 1.0),
    "debt_weight": (0.0, 1.0),
    "market_equity": (0.0, 1e15),
    "market_debt": (0.0, 1e15),
    "shares_outstanding": (1.0, 1e12),
    "share_price": (0.0, 1e7),
}


def _pct(v: float | None) -> str:
    return f"{v:.2%}" if v is not None else "n/a"


def build_assumptions(
    historical: HistoricalAnalysis,
    periods: list[PeriodData],
    market: MarketSnapshot,
    *,
    private: bool = False,
    excel_values: dict[str, float] | None = None,
    default_rf: float | None = None,
) -> list[Assumption]:
    """Assemble the default assumption set with full provenance."""
    excel_values = excel_values or {}
    out: list[Assumption] = {}

    hist = {a.key: a for a in historical.proposed_assumptions}
    latest = periods[-1].metrics if periods else {}
    latest_vals = {k: sv.value for k, sv in latest.items() if sv.value is not None}

    def model_value(key: str) -> tuple[float | None, str, float | None]:
        """(default value, source label, historical value)"""
        if key in hist:
            a = hist[key]
            return a.model_estimate, a.source, a.historical_value
        return None, "Model", None

    # ---- forecast drivers ---------------------------------------------------
    for key, label, unit in (
        ("revenue_growth", "Revenue Growth", Unit.PERCENT),
        ("ebit_margin", "EBIT Margin", Unit.PERCENT),
        ("da_pct", "D&A / Revenue", Unit.PERCENT),
        ("capex_pct", "CapEx / Revenue", Unit.PERCENT),
        ("nwc_pct", "NWC / Revenue", Unit.PERCENT),
    ):
        est, src, hv = model_value(key)
        user = excel_values.get(key)
        out[key] = Assumption(
            key=key, label=label, group="forecast",
            value=user if user is not None else est,
            unit=unit, historical_value=hv,
            model_estimate=est, user_value=user,
            source_type=(SourceType.USER_INPUT if user is not None
                         else SourceType.MODEL_ASSUMPTION),
            source=("Uploaded Excel / user input" if user is not None else src),
            status=(ValueStatus.USER_DATA if user is not None else ValueStatus.ESTIMATED),
            note=(None if user is not None else hist.get(key).note if key in hist else None),
            min_value=BOUNDS[key][0], max_value=BOUNDS[key][1],
        )

    # ---- tax rate (shared by WACC + FCF) ------------------------------------
    est_tax, _, hv_tax = model_value("tax_rate")
    stat_default = 0.21
    user_tax = excel_values.get("tax_rate")
    final_tax = user_tax if user_tax is not None else est_tax
    out["tax_rate"] = Assumption(
        key="tax_rate", label="Tax Rate", group="wacc",
        value=final_tax if final_tax is not None else stat_default,
        unit=Unit.PERCENT, historical_value=hv_tax,
        model_estimate=est_tax if est_tax is not None else stat_default,
        user_value=user_tax,
        source_type=(SourceType.USER_INPUT if user_tax is not None
                     else SourceType.MODEL_ASSUMPTION),
        source=("Uploaded Excel / user input" if user_tax is not None
                else "Historical analysis" if est_tax is not None else "Statutory default (US federal 21%)"),
        status=(ValueStatus.USER_DATA if user_tax is not None else ValueStatus.ESTIMATED),
        note=("US statutory 21% used because no historical effective rate was derivable."
              if est_tax is None and user_tax is None else
              "Effective rate = income tax expense / EBT."),
        min_value=0.0, max_value=0.75,
    )

    # ---- WACC inputs ---------------------------------------------------------
    rf = market.risk_free_rate
    if rf is None and "risk_free_rate" in excel_values:
        rf = excel_values["risk_free_rate"]
        rf_source, rf_status, rf_type = "User input", ValueStatus.USER_DATA, SourceType.USER_INPUT
    elif rf is not None:
        rf_source, rf_status, rf_type = (market.risk_free_source or "Public API"), ValueStatus.RETRIEVED, SourceType.PUBLIC_API
    else:
        rf = default_rf
        rf_source, rf_status, rf_type = ("Model default — provider unavailable",
                                         ValueStatus.ESTIMATED, SourceType.MODEL_ASSUMPTION)
    out["risk_free_rate"] = Assumption(
        key="risk_free_rate", label="Risk-Free Rate", group="wacc", value=rf,
        unit=Unit.PERCENT, model_estimate=rf, user_value=excel_values.get("risk_free_rate"),
        source_type=rf_type, source=rf_source, status=rf_status,
        note="10-year US Treasury yield (DGS10) unless overridden.",
        min_value=-0.02, max_value=0.25,
    )

    beta = market.beta
    beta_user = excel_values.get("beta")
    if beta_user is not None:
        out["beta"] = Assumption(
            key="beta", label="Beta", group="wacc", value=beta_user, unit=Unit.RATIO,
            model_estimate=beta, user_value=beta_user, historical_value=beta,
            source_type=SourceType.USER_INPUT, source="User input (uploaded Excel/entered)",
            status=ValueStatus.USER_DATA,
            note="Manual beta supplied by the user.", min_value=-1.0, max_value=4.0,
        )
    elif beta is not None:
        out["beta"] = Assumption(
            key="beta", label="Beta", group="wacc", value=beta, unit=Unit.RATIO,
            model_estimate=beta,
            source_type=SourceType.PUBLIC_API, source="Yahoo Finance price history (OLS vs SPY)",
            source_url=f"https://finance.yahoo.com/quote/{market.beta_source or ''}".split("?")[0],
            status=ValueStatus.RETRIEVED,
            note=market.beta_source,
            min_value=-1.0, max_value=4.0,
        )
    else:
        out["beta"] = Assumption(
            key="beta", label="Beta", group="wacc", value=None, unit=Unit.RATIO,
            source_type=SourceType.MODEL_ASSUMPTION, source="Missing — no market data",
            status=ValueStatus.MISSING,
            note=("No observable beta (private company or provider unavailable). "
                  "Choose Comparable Companies or Manual Beta to proceed."),
            min_value=-1.0, max_value=4.0,
        )

    mrp = excel_values.get("market_risk_premium", 0.050)
    out["market_risk_premium"] = Assumption(
        key="market_risk_premium", label="Market Risk Premium", group="wacc", value=mrp,
        unit=Unit.PERCENT, model_estimate=0.050, user_value=excel_values.get("market_risk_premium"),
        source_type=(SourceType.USER_INPUT if "market_risk_premium" in excel_values
                     else SourceType.MODEL_ASSUMPTION),
        source=("User input" if "market_risk_premium" in excel_values else "Model default (5.00%)"),
        status=(ValueStatus.USER_DATA if "market_risk_premium" in excel_values else ValueStatus.ESTIMATED),
        note="Equity risk premium used in CAPM; no free provider publishes a canonical MRP.",
        min_value=0.0, max_value=0.20,
    )

    # cost of debt: interest-bearing capacity first
    interest = latest_vals.get("interest_expense")
    debt = latest_vals.get("total_debt")
    derived_rd = None
    rd_note = None
    if interest and debt and debt > 0:
        derived_rd = interest / debt
        rd_note = f"Interest expense {interest:,.0f} / total debt {debt:,.0f}."
    rd = excel_values.get("cost_of_debt", derived_rd)
    if rd is None:
        rd = 0.05
        rd_note = ("No debt or interest data found — 5.00% placeholder set explicitly. "
                   "It only affects WACC if a debt weight is used.")
        rd_type, rd_status = SourceType.MODEL_ASSUMPTION, ValueStatus.ESTIMATED
        rd_source = "Model default"
    elif "cost_of_debt" in excel_values:
        rd_type, rd_status = SourceType.USER_INPUT, ValueStatus.USER_DATA
        rd_source = "User input"
    else:
        rd_type, rd_status = SourceType.MODEL_CALCULATION, ValueStatus.CALCULATED
        rd_source = "Derived from reported interest expense / total debt"
    out["cost_of_debt"] = Assumption(
        key="cost_of_debt", label="Cost of Debt", group="wacc", value=rd,
        unit=Unit.PERCENT, model_estimate=derived_rd, user_value=excel_values.get("cost_of_debt"),
        source_type=rd_type, source=rd_source, status=rd_status, note=rd_note,
        min_value=0.0, max_value=0.50,
    )

    # capital structure: market equity
    me = market.market_cap
    if me is None and market.share_price and latest_vals.get("shares_outstanding"):
        me = market.share_price * latest_vals["shares_outstanding"]
    if me is None and "share_price" in excel_values and latest_vals.get("shares_outstanding"):
        me = excel_values["share_price"] * latest_vals["shares_outstanding"]
    out["market_equity"] = Assumption(
        key="market_equity", label="Market Value of Equity", group="wacc",
        value=me, unit=Unit.CURRENCY,
        model_estimate=me,
        source_type=(SourceType.MODEL_CALCULATION if me is not None else SourceType.MODEL_ASSUMPTION),
        source=("Latest close x shares outstanding" if me else "Missing"),
        status=(ValueStatus.CALCULATED if me is not None else ValueStatus.MISSING),
        note=("Private company: enter an Estimated Equity Value to use market weights."
              if private and me is None else "Market capitalisation."),
        editable=True,
    )
    md = debt
    out["market_debt"] = Assumption(
        key="market_debt", label="Market Value of Debt", group="wacc", value=md,
        unit=Unit.CURRENCY, model_estimate=md,
        source_type=SourceType.MODEL_CALCULATION if md is not None else SourceType.MODEL_ASSUMPTION,
        source=("Total debt from latest balance sheet (book value proxy)"
                if md is not None else "No debt reported — set to 0"),
        status=ValueStatus.CALCULATED if md is not None else ValueStatus.ESTIMATED,
        note="Book value of debt is the standard proxy when market values are unavailable.",
    )

    target_de = excel_values.get("target_de")
    if target_de is None and md and me:
        target_de = md / me
    out["target_de"] = Assumption(
        key="target_de", label="Target D/E", group="wacc",
        value=target_de if target_de is not None else 0.0, unit=Unit.RATIO,
        model_estimate=(md / me if md and me else 0.0), user_value=excel_values.get("target_de"),
        source_type=(SourceType.USER_INPUT if "target_de" in excel_values
                     else SourceType.MODEL_CALCULATION if md and me else SourceType.MODEL_ASSUMPTION),
        source=("User input" if "target_de" in excel_values
                else "Total debt / market equity" if md and me else "No debt — D/E = 0"),
        status=(ValueStatus.USER_DATA if "target_de" in excel_values else ValueStatus.CALCULATED),
        min_value=0.0, max_value=5.0,
    )

    # ---- terminal + general -------------------------------------------------
    out["terminal_growth"] = Assumption(
        key="terminal_growth", label="Terminal Growth Rate", group="terminal",
        value=excel_values.get("terminal_growth", 0.025), unit=Unit.PERCENT,
        model_estimate=0.025, user_value=excel_values.get("terminal_growth"),
        source_type=(SourceType.USER_INPUT if "terminal_growth" in excel_values
                     else SourceType.MODEL_ASSUMPTION),
        source=("User input" if "terminal_growth" in excel_values else "Model default (2.50%)"),
        status=(ValueStatus.USER_DATA if "terminal_growth" in excel_values else ValueStatus.ESTIMATED),
        note="Long-run growth; must stay below WACC. Default below long-run nominal GDP intuition.",
        min_value=-0.05, max_value=0.10,
    )
    out["exit_multiple"] = Assumption(
        key="exit_multiple", label="Exit EV/EBITDA Multiple", group="terminal",
        value=excel_values.get("exit_multiple", 10.0), unit=Unit.MULTIPLE,
        model_estimate=10.0, user_value=excel_values.get("exit_multiple"),
        source_type=(SourceType.USER_INPUT if "exit_multiple" in excel_values
                     else SourceType.MODEL_ASSUMPTION),
        source=("User input" if "exit_multiple" in excel_values else "Model default (10.0x)"),
        status=(ValueStatus.USER_DATA if "exit_multiple" in excel_values else ValueStatus.ESTIMATED),
        note="Used by the exit-multiple terminal method; comparables median is shown when available.",
        min_value=0.5, max_value=60.0,
    )

    shares = latest_vals.get("shares_outstanding") or excel_values.get("shares_outstanding")
    out["shares_outstanding"] = Assumption(
        key="shares_outstanding", label="Shares Outstanding", group="general",
        value=shares, unit=Unit.COUNT,
        source_type=(SourceType.PUBLIC_API if latest_vals.get("shares_outstanding")
                     else SourceType.USER_INPUT if shares else SourceType.MODEL_ASSUMPTION),
        source=("SEC EDGAR dei:EntityCommonStockSharesOutstanding"
                if latest_vals.get("shares_outstanding")
                else "User input" if shares else "Missing"),
        status=(ValueStatus.RETRIEVED if latest_vals.get("shares_outstanding")
                else ValueStatus.USER_DATA if shares else ValueStatus.MISSING),
        note=None if shares else "Required for implied share price — add it on the Data Review page.",
        min_value=1.0,
    )
    price = market.share_price or excel_values.get("share_price")
    out["share_price"] = Assumption(
        key="share_price", label="Current Share Price", group="general",
        value=price, unit=Unit.CURRENCY,
        source_type=(SourceType.PUBLIC_API if market.share_price
                     else SourceType.USER_INPUT if price else SourceType.MODEL_ASSUMPTION),
        source=("Yahoo Finance latest close" if market.share_price
                else "User input" if price else "Missing"),
        status=(ValueStatus.RETRIEVED if market.share_price
                else ValueStatus.USER_DATA if price else ValueStatus.MISSING),
        note=None if price else "Used only to compute upside/downside; private companies may leave blank.",
    )

    out["forecast_years"] = Assumption(
        key="forecast_years", label="Forecast Period (years)", group="general",
        value=float(excel_values.get("forecast_years", 5)), unit=Unit.COUNT,
        model_estimate=5.0, user_value=excel_values.get("forecast_years"),
        source_type=SourceType.MODEL_ASSUMPTION, source="Model default",
        status=ValueStatus.ESTIMATED, min_value=1, max_value=15,
    )

    # cost of equity placeholder — recomputed by the WACC stage from method
    out["cost_of_equity"] = Assumption(
        key="cost_of_equity", label="Cost of Equity", group="wacc",
        value=None, unit=Unit.PERCENT, model_estimate=None,
        source_type=SourceType.MODEL_CALCULATION, source="CAPM (computed in WACC stage)",
        status=ValueStatus.CALCULATED, editable=True,
        note="Set 'Cost of Equity Method = Manual Expected Return' to override.",
        min_value=0.0, max_value=0.60,
    )

    return [out[k] for k in out]


def apply_overrides(assumptions: list[Assumption], overrides: dict[str, float],
                    *, clear: list[str] | None = None) -> list[Assumption]:
    """Apply user overrides with validation; overrides are never hidden."""
    by_key = {a.key: a for a in assumptions}
    for key in (clear or []):
        a = by_key.get(key)
        if a is None:
            raise ValidationError(f"Unknown assumption '{key}'",
                                  hint=f"Known keys: {', '.join(sorted(by_key))}")
        a.user_value = None
        a.value = a.model_estimate
        a.source_type = SourceType.MODEL_ASSUMPTION
        a.status = ValueStatus.ESTIMATED
    for key, value in overrides.items():
        a = by_key.get(key)
        if a is None:
            raise ValidationError(
                f"Unknown assumption '{key}'",
                hint=f"Known keys: {', '.join(sorted(by_key))}")
        if value is None or (isinstance(value, float) and value != value):  # NaN
            raise ValidationError(f"Assumption '{key}' has no numeric value")
        lo, hi = BOUNDS.get(key, (-1e15, 1e15))
        if not lo <= value <= hi:
            raise ValidationError(
                f"Override for '{key}' = {value} outside plausible range [{lo}, {hi}]",
                hint="Rates are decimals: enter 0.08 for 8%.")
        a.user_value = float(value)
        a.value = float(value)
        a.source_type = SourceType.USER_OVERRIDE
        a.status = ValueStatus.OVERRIDE
        a.note = (a.note + " | " if a.note else "") + "USER OVERRIDE applied"
    # recompute final value where not overridden
    for a in assumptions:
        if a.user_value is None:
            a.value = a.model_estimate if a.model_estimate is not None else a.value
    return assumptions


def get_values(assumptions: list[Assumption]) -> dict[str, float | None]:
    return {a.key: a.value for a in assumptions}


def mark_calculated(assumptions: list[Assumption], key: str, value: float,
                    source: str, note: str | None = None) -> None:
    """Record a computed input (e.g. CAPM cost of equity) without hiding it."""
    for a in assumptions:
        if a.key == key:
            if a.source_type == SourceType.USER_OVERRIDE:
                return  # user override wins
            a.value = value
            a.model_estimate = value
            a.source_type = SourceType.MODEL_CALCULATION
            a.source = source
            a.status = ValueStatus.CALCULATED
            if note:
                a.note = note
            return
