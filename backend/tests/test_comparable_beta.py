"""Comparable beta must unlever peers with gross debt and their own tax rates.

Using (EV - market cap) as D/E treats NET debt as gross debt and applying the
target's tax rate to every peer silently misstates the Hamada unlevering.
"""
from datetime import date

import pytest

from app.schemas.company import PeriodData
from app.schemas.valuation import PeerMetrics, ValuationOptions
from app.services.wacc import build_wacc
from app.valuation import comparable_beta_estimate


def _periods() -> list[PeriodData]:
    return [PeriodData(period="FY2025", fiscal_year=2025, end_date=date(2025, 12, 31))]


def _values() -> dict[str, float]:
    return {
        "tax_rate": 0.21,
        "risk_free_rate": 0.04,
        "market_risk_premium": 0.05,
        "cost_of_debt": 0.06,
        "target_de": 0.30,
        "market_equity": 1e9,
        "market_debt": 2e8,
        "terminal_growth": 0.025,
    }


def _options() -> ValuationOptions:
    return ValuationOptions(beta_method="comparables", cost_of_equity_method="capm",
                            capital_structure_method="target")


def _peers() -> list[PeerMetrics]:
    return [
        # Gross debt 500 / equity 1000 = 0.50; net debt would be 300/1000 = 0.30
        PeerMetrics(ticker="AAA", levered_beta=1.2, market_cap=1000.0, total_debt=500.0,
                    cash=200.0, ev=1300.0, tax_rate=0.25),
        # Gross debt 200 / equity 800 = 0.25; net debt would be 80/800 = 0.10
        PeerMetrics(ticker="BBB", levered_beta=0.9, market_cap=800.0, total_debt=200.0,
                    cash=120.0, ev=880.0, tax_rate=0.20),
    ]


def test_comparable_beta_uses_gross_debt_and_peer_tax():
    out = build_wacc(_values(), _options(), _periods(), peers=_peers())

    expected = comparable_beta_estimate(
        [("AAA", 1.2, 500 / 1000, 0.25), ("BBB", 0.9, 200 / 800, 0.20)],
        target_de=0.30, target_tax_rate=0.21, method="median",
    )
    assert out.beta.value == pytest.approx(expected.relevered_beta, rel=1e-9)

    details = {d.ticker: d for d in out.beta_details}
    assert details["AAA"].debt_equity == pytest.approx(0.50)
    assert details["BBB"].debt_equity == pytest.approx(0.25)
    assert details["AAA"].tax_rate == pytest.approx(0.25)
    assert details["BBB"].tax_rate == pytest.approx(0.20)
    # no fallback warnings when gross debt and peer tax are available
    assert not any("net debt" in w for w in out.warnings)
    assert not any("Peer effective tax" in w for w in out.warnings)


def test_comparable_beta_flags_net_debt_fallback():
    peers = [PeerMetrics(ticker="CCC", levered_beta=1.1, market_cap=1000.0,
                         ev=1200.0, cash=50.0, total_debt=None, tax_rate=None)]
    out = build_wacc(_values(), _options(), _periods(), peers=peers)

    assert out.beta_details[0].debt_equity == pytest.approx(0.20)
    assert any("net debt" in w.lower() for w in out.warnings)
    assert any("tax rate unavailable" in w for w in out.warnings)
