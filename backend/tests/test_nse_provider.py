"""NSE India (Mode B) — XBRL parsing, routing and provenance.

The XBRL fixtures mirror the two shapes NSE actually serves:

  * integrated filings (2025+): real 12-month contexts + period-end instants
    (and prior-year comparatives that must be ignored);
  * legacy filings: cumulative figures under an undeclared ``FourD`` context
    while segment details sit in dimensional contexts.

No network access is required — all documents are inline fixtures.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import ProviderError
from app.data.providers.base import MarketSnapshot
from app.data.providers.nse import (
    AnnualFiling,
    _build_period,
    _parse_bhavcopy,
    _select_filings,
    parse_xbrl,
)
from app.data.providers.public_company import MARKET_IN, MARKET_US, resolve_market
from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.schemas.company import PeriodData
from app.services.assumptions import build_assumptions
from app.services.historical import analyze

NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin" '
    'xmlns:iso4217="http://www.xbrl.org/2003/iso4217"'
)


def _context(cid: str, start: str | None = None, end: str | None = None,
             instant: str | None = None, member: str | None = None) -> str:
    period = (f"<xbrli:period><xbrli:startDate>{start}</xbrli:startDate>"
              f"<xbrli:endDate>{end}</xbrli:endDate></xbrli:period>"
              if start else
              f"<xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period>")
    scenario = (f'<xbrli:scenario><xbrldi:explicitMember dimension="in-bse-fin:Axis">'
                f"in-bse-fin:{member}</xbrldi:explicitMember></xbrli:scenario>"
                if member else "")
    return (f'<xbrli:context id="{cid}"><xbrli:entity>'
            f'<xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">TEST</xbrli:identifier>'
            f"</xbrli:entity>{period}{scenario}</xbrli:context>")


def _fact(tag: str, context: str, value: float | int, unit: str = "INR") -> str:
    return (f'<in-bse-fin:{tag} contextRef="{context}" unitRef="{unit}" decimals="0">'
            f"{value}</in-bse-fin:{tag}>")


INTEGRATED = (
    f"<xbrli:xbrl {NS}>"
    + _context("FY", "2025-04-01", "2026-03-31")
    + _context("Q4", "2026-01-01", "2026-03-31")
    + _context("PRIOR_FY", "2024-04-01", "2025-03-31")
    + _context("END", instant="2026-03-31")
    + _context("PRIOR_END", instant="2025-03-31")
    + _context("SEG", "2025-04-01", "2026-03-31", member="SegmentMember")
    + '<xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>'
    + _fact("RevenueFromOperations", "FY", 1_000_000)
    + _fact("RevenueFromOperations", "Q4", 300_000)
    + _fact("RevenueFromOperations", "PRIOR_FY", 900_000)
    + _fact("FinanceCosts", "FY", 10_000)
    + _fact("ProfitBeforeTax", "FY", 110_000)
    + _fact("TaxExpense", "FY", 28_000)
    + _fact("ProfitLossForPeriod", "FY", 82_000)
    + _fact("DepreciationDepletionAndAmortisationExpense", "FY", 20_000)
    + _fact("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "FY", 55_000)
    + _fact("CashFlowsFromUsedInOperatingActivities", "FY", 150_000)
    + _fact("PaidUpValueOfEquityShareCapital", "FY", 100_000)
    + _fact("FaceValueOfEquityShareCapital", "FY", 10)
    + _fact("CashAndCashEquivalents", "END", 50_000)
    + _fact("CashAndCashEquivalents", "PRIOR_END", 40_000)
    + _fact("BorrowingsCurrent", "END", 5_000)
    + _fact("BorrowingsNoncurrent", "END", 20_000)
    + _fact("Assets", "END", 800_000)
    + _fact("Assets", "PRIOR_END", 700_000)
    + _fact("Assets", "SEG", 123)  # dimensional fact must never be used
    + "</xbrli:xbrl>"
)

# Legacy NSE document: OneD/FourD are referenced but never declared.
LEGACY = (
    f"<xbrli:xbrl {NS}>"
    + _context("SEG", "2020-04-01", "2021-03-31", member="SegmentMember")
    + _fact("RevenueFromOperations", "OneD", 437_050)
    + _fact("RevenueFromOperations", "FourD", 1_641_770)
    + _fact("ProfitBeforeTax", "FourD", 437_600)
    + _fact("ProfitLossForPeriod", "FourD", 325_620)
    + _fact("PaidUpValueOfEquityShareCapital", "FourD", 37_000)
    + _fact("FaceValueOfEquityShareCapital", "FourD", 10)
    + '<in-bse-fin:DateOfStartOfReportingPeriod contextRef="FourD">2020-04-01'
      "</in-bse-fin:DateOfStartOfReportingPeriod>"
    + '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="FourD">2021-03-31'
      "</in-bse-fin:DateOfEndOfReportingPeriod>"
    + _fact("SegmentRevenue", "SEG", 999_999)
    + "</xbrli:xbrl>"
)


def _filing(**overrides) -> AnnualFiling:
    base = dict(symbol="TEST", fiscal_year=2026, period_end=date(2026, 3, 31),
                consolidated=True, audited=True,
                xbrl_url="https://nsearchives.nseindia.com/corporate/xbrl/TEST.xml",
                company_name="Test Industries Limited", broadcast="09-Apr-2026")
    base.update(overrides)
    return AnnualFiling(**base)


# --- parsing ---------------------------------------------------------------

def test_integrated_xbrl_picks_full_year_and_latest_instant():
    statements = parse_xbrl(INTEGRATED)
    assert statements.period_start == date(2025, 4, 1)
    assert statements.period_end == date(2026, 3, 31)
    assert statements.legacy_cumulative is False
    assert statements.flow["RevenueFromOperations"] == pytest.approx(1_000_000)
    assert statements.instant["CashAndCashEquivalents"] == pytest.approx(50_000)
    assert statements.instant["Assets"] == pytest.approx(800_000)  # not the 2025 comparative


def test_legacy_xbrl_uses_cumulative_four_d_column():
    statements = parse_xbrl(LEGACY)
    assert statements.period_start == date(2020, 4, 1)
    assert statements.period_end == date(2021, 3, 31)
    assert statements.flow["RevenueFromOperations"] == pytest.approx(1_641_770)
    # segment (dimensional) facts never become company totals
    assert "SegmentRevenue" not in statements.flow


def test_period_builds_derived_metrics_with_provenance():
    warnings: list[str] = []
    period = _build_period(_filing(), parse_xbrl(INTEGRATED), warnings)
    assert period is not None
    assert period.currency == "INR"
    assert period.period == "FY2026"
    assert period.end_date == date(2026, 3, 31)

    g = period.value
    # EBIT = PBT + finance costs; EBITDA = EBIT + D&A
    assert g("ebit") == pytest.approx(120_000)
    assert g("ebitda") == pytest.approx(140_000)
    assert g("total_debt") == pytest.approx(25_000)
    assert g("capex") == pytest.approx(55_000)
    # Shares = paid-up capital / face value
    assert g("shares_outstanding") == pytest.approx(10_000)

    assert period.metrics["revenue"].source_type is SourceType.PUBLIC_API
    assert "RevenueFromOperations" in period.metrics["revenue"].source
    assert period.metrics["revenue"].currency == "INR"
    assert period.metrics["ebit"].source_type is SourceType.MODEL_CALCULATION
    assert period.metrics["ebit"].status is ValueStatus.CALCULATED
    assert period.metrics["shares_outstanding"].unit is Unit.COUNT


def test_unparseable_xbrl_raises_provider_error():
    with pytest.raises(ProviderError):
        parse_xbrl("<not-xbrl")


# --- filing selection ------------------------------------------------------

def test_consolidated_audited_filing_wins_per_year():
    filings = [
        _filing(consolidated=False, broadcast="09-Apr-2026"),
        _filing(consolidated=True, broadcast="08-Apr-2026"),
        _filing(fiscal_year=2025, consolidated=False, period_end=date(2025, 3, 31)),
    ]
    chosen = _select_filings(filings, years=8)
    assert [f.fiscal_year for f in chosen] == [2025, 2026]
    assert chosen[-1].consolidated is True


# --- routing ---------------------------------------------------------------

def test_ns_suffix_selects_nse():
    assert resolve_market("reliance.ns") == ("RELIANCE", MARKET_IN)
    assert resolve_market("TCS.NSE") == ("TCS", MARKET_IN)


def test_explicit_market_and_default():
    assert resolve_market("TCS", "IN") == ("TCS", MARKET_IN)
    assert resolve_market("AAPL") == ("AAPL", MARKET_US)
    assert resolve_market("AAPL", "US") == ("AAPL", MARKET_US)


def test_bse_only_symbol_is_rejected():
    with pytest.raises(ProviderError):
        resolve_market("RELIANCE.BO")


# --- bhavcopy --------------------------------------------------------------

BHAV = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
    "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, "
    "DELIV_QTY, DELIV_PER\n"
    "TCS, EQ, 30-Oct-2026, 2478.00, 2495.20, 2527.70, 2494.20, 2502.60, 2502.60, "
    "2513.04, 3016983, 75818.09, 119512, 1420735, 47.09\n"
    "TCS, BE, 30-Oct-2026, 2478.00, 2495.20, 2527.70, 2494.20, 2501.10, 2501.10, "
    "2513.04, 10, 1.0, 1, 1, 1.0\n"
)


def test_bhavcopy_close_is_parsed_for_the_symbol():
    assert _parse_bhavcopy(BHAV, "TCS") == pytest.approx(2502.60)
    assert _parse_bhavcopy(BHAV, "INFY") is None


# --- provenance in assumptions --------------------------------------------

def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.PUBLIC_API, status=ValueStatus.RETRIEVED)


def _periods() -> list[PeriodData]:
    out, rev = [], 1_000_000.0
    for i, y in enumerate(range(2025, 2027)):
        if i:
            rev *= 1.1
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 3, 31),
                              currency="INR", metrics={
            "revenue": _sv(rev), "ebit": _sv(rev * .2), "ebt": _sv(rev * .18),
            "income_tax_expense": _sv(rev * .045), "net_income": _sv(rev * .135),
            "da": _sv(rev * .03), "capex": _sv(rev * .04), "cash": _sv(rev * .1),
            "total_debt": _sv(rev * .05), "shares_outstanding": _sv(10_000, Unit.COUNT),
        }))
    return out


def test_nse_provenance_flows_into_assumptions():
    market = MarketSnapshot(
        market="IN", risk_free_rate=0.0706,
        risk_free_source="FRED INDIRLTLT01STM (India 10Y G-Sec) as of 2026-09-01 (7.06%)",
        beta=1.25, beta_provider="NSE India (month-end bhavcopy closes vs NIFTY 50)",
        beta_source="OLS regression vs NIFTY 50 — n=24", share_price=2_500.0,
        price_provider="NSE India (official bhavcopy close)",
        shares_outstanding=10_000, shares_provider="NSE India XBRL (paid-up equity capital / face value)",
        market_cap=25_000_000,
    )
    assumptions = {a.key: a for a in build_assumptions(
        analyze(_periods(), private=False), _periods(), market, excel_values={})}

    assert assumptions["risk_free_rate"].source_type is SourceType.PUBLIC_API
    assert "INDIRLTLT01STM" in assumptions["risk_free_rate"].source
    assert assumptions["beta"].source == "NSE India (month-end bhavcopy closes vs NIFTY 50)"
    assert assumptions["beta"].value == pytest.approx(1.25)
    assert assumptions["share_price"].source == "NSE India (official bhavcopy close)"
    assert assumptions["shares_outstanding"].source.startswith("NSE India XBRL")
    # India ERP default is a labelled model assumption, not a hidden constant
    assert assumptions["market_risk_premium"].value == pytest.approx(0.065)
    assert assumptions["market_risk_premium"].source_type is SourceType.MODEL_ASSUMPTION
    assert "India" in assumptions["market_risk_premium"].source
