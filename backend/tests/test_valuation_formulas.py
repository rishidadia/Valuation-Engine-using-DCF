"""Unit tests for every core financial formula (spec section 17).

These functions must never depend on an LLM — the tests prove the math.
"""
import math

import numpy as np
import pytest

from app.core.errors import TerminalValueError, ValidationError
from app.valuation import (
    aggregate_beta,
    calculate_after_tax_cost_of_debt,
    calculate_capm,
    calculate_capital_weights,
    calculate_cost_of_debt,
    calculate_enterprise_value,
    calculate_equity_value,
    calculate_fcf,
    calculate_implied_share_price,
    calculate_nopat,
    calculate_relevered_beta,
    calculate_sensitivity_matrix,
    calculate_terminal_value_exit_multiple,
    calculate_terminal_value_perpetuity,
    calculate_unlevered_beta,
    calculate_wacc,
    discount_factors,
    fcf_components,
    regression_beta,
    run_dcf,
    tornado_swing,
)


# ---------------- CAPM ----------------

class TestCapm:
    def test_textbook_value(self):
        r = calculate_capm(0.038, 1.15, 0.052)
        assert r.cost_of_equity == pytest.approx(0.038 + 1.15 * 0.052)
        assert r.cost_of_equity == pytest.approx(0.0978)

    def test_zero_beta_equals_risk_free(self):
        assert calculate_capm(0.04, 0.0, 0.05).cost_of_equity == pytest.approx(0.04)

    def test_rejects_percent_as_decimal(self):
        with pytest.raises(ValidationError):
            calculate_capm(3.8, 1.15, 5.2)  # 380% risk-free: clearly wrong input

    def test_rejects_extreme_beta(self):
        with pytest.raises(ValidationError):
            calculate_capm(0.04, 9.9, 0.05)

    def test_negative_beta_allowed_within_bounds(self):
        r = calculate_capm(0.04, -0.3, 0.05)
        assert r.cost_of_equity == pytest.approx(0.04 - 0.015)


# ---------------- Cost of debt ----------------

class TestCostOfDebt:
    def test_weighted_instruments(self):
        # $25M @ 5.5%, $15M @ 6.0% -> (25*5.5 + 15*6)/40 = 5.6875%
        rd = calculate_cost_of_debt([(25e6, 0.055), (15e6, 0.06)])
        assert rd == pytest.approx((25 * 0.055 + 15 * 0.06) / 40)

    def test_manual(self):
        assert calculate_cost_of_debt(manual_rate=0.07) == pytest.approx(0.07)

    def test_requires_input(self):
        with pytest.raises(ValidationError):
            calculate_cost_of_debt()

    def test_rejects_absurd_rate(self):
        with pytest.raises(ValidationError):
            calculate_cost_of_debt(manual_rate=0.9)

    def test_rejects_zero_total(self):
        with pytest.raises(ValidationError):
            calculate_cost_of_debt([(0.0, 0.05)])

    def test_after_tax(self):
        assert calculate_after_tax_cost_of_debt(0.08, 0.25) == pytest.approx(0.06)

    def test_after_tax_zero_debt_rate(self):
        assert calculate_after_tax_cost_of_debt(0.0, 0.21) == 0.0

    def test_after_tax_rejects_bad_tax(self):
        with pytest.raises(ValidationError):
            calculate_after_tax_cost_of_debt(0.06, 1.5)


# ---------------- Weights & WACC ----------------

class TestWacc:
    def test_weights(self):
        w = calculate_capital_weights(80e9, 20e9)
        assert w.equity_weight == pytest.approx(0.8)
        assert w.debt_weight == pytest.approx(0.2)

    def test_weights_all_equity(self):
        w = calculate_capital_weights(100e9, 0.0)
        assert w.equity_weight == pytest.approx(1.0)
        assert w.debt_weight == pytest.approx(0.0)

    def test_weights_reject_zero_total(self):
        with pytest.raises(ValidationError):
            calculate_capital_weights(0, 0)

    def test_weights_reject_negative(self):
        with pytest.raises(ValidationError):
            calculate_capital_weights(-1, 5)

    def test_wacc_textbook(self):
        # 0.8*10% + 0.2*6%*(1-0.25) = 8% + 0.9% = 8.9%
        w = calculate_wacc(0.8, 0.2, 0.10, 0.06, 0.25)
        assert w == pytest.approx(0.8 * 0.10 + 0.2 * 0.06 * 0.75)

    def test_wacc_pure_equity(self):
        assert calculate_wacc(1.0, 0.0, 0.11, 0.05, 0.21) == pytest.approx(0.11)

    def test_wacc_weights_must_sum_to_one(self):
        with pytest.raises(ValidationError):
            calculate_wacc(0.6, 0.2, 0.10, 0.06, 0.25)

    def test_wacc_rejects_negative_rate(self):
        with pytest.raises(ValidationError):
            calculate_wacc(0.7, 0.3, 0.10, -0.01, 0.25)

    def test_wacc_rejects_bad_tax(self):
        with pytest.raises(ValidationError):
            calculate_wacc(0.7, 0.3, 0.10, 0.06, 0.95)


# ---------------- NOPAT / FCF ----------------

class TestFcf:
    def test_nopat(self):
        assert calculate_nopat(100e6, 0.25) == pytest.approx(75e6)

    def test_fcf_textbook(self):
        # EBIT 100, T 25%, D&A 20, CapEx 30, dNWC 5 -> 75 + 20 - 30 - 5 = 60
        assert calculate_fcf(100e6, 0.25, 20e6, 30e6, 5e6) == pytest.approx(60e6)

    def test_fcf_components_breakdown(self):
        c = fcf_components(100e6, 0.25, 20e6, 30e6, 5e6)
        assert c.nopat == pytest.approx(75e6)
        assert c.tax_expense == pytest.approx(25e6)
        assert c.fcf == pytest.approx(60e6)
        assert "FCF =" in c.formula

    def test_fcf_negative_ebit(self):
        # Loss-making company: negative NOPAT still flows through
        assert calculate_fcf(-40e6, 0.21, 10e6, 5e6, 0.0) == pytest.approx(-40e6 * 0.79 + 10e6 - 5e6)

    def test_fcf_missing_component(self):
        with pytest.raises(ValidationError):
            calculate_fcf(100e6, 0.25, None, 30e6, 5e6)

    def test_nopat_bad_tax(self):
        with pytest.raises(ValidationError):
            calculate_nopat(100e6, -0.1)


# ---------------- Terminal value ----------------

class TestTerminalValue:
    def test_perpetuity(self):
        # FCF 100, g 3%, WACC 8% -> 100*1.03/0.05 = 2060
        tv = calculate_terminal_value_perpetuity(100e6, 0.08, 0.03)
        assert tv == pytest.approx(100e6 * 1.03 / 0.05)

    def test_perpetuity_wacc_equals_g_raises(self):
        with pytest.raises(TerminalValueError):
            calculate_terminal_value_perpetuity(100e6, 0.05, 0.05)

    def test_perpetuity_wacc_below_g_raises(self):
        with pytest.raises(TerminalValueError) as ei:
            calculate_terminal_value_perpetuity(100e6, 0.03, 0.05)
        assert "must be strictly below WACC" in str(ei.value.detail)

    def test_exit_multiple(self):
        assert calculate_terminal_value_exit_multiple(250e6, 12.0) == pytest.approx(3e9)

    def test_exit_multiple_rejects_zero(self):
        with pytest.raises(ValidationError):
            calculate_terminal_value_exit_multiple(250e6, 0.0)

    def test_exit_multiple_rejects_missing_ebitda(self):
        with pytest.raises(ValidationError):
            calculate_terminal_value_exit_multiple(None, 10.0)


# ---------------- EV / equity / price ----------------

class TestEquityBridge:
    def test_ev(self):
        assert calculate_enterprise_value(500e6, 1_500e6) == pytest.approx(2_000e6)

    def test_equity_bridge(self):
        # EV 2000 + cash 100 - debt 300 = 1800
        assert calculate_equity_value(2_000e6, 100e6, 300e6) == pytest.approx(1_800e6)

    def test_equity_bridge_missing_cash_debt_treated_as_zero(self):
        assert calculate_equity_value(1_000e6, None, None) == pytest.approx(1_000e6)

    def test_implied_price(self):
        assert calculate_implied_share_price(1_800e6, 5_000e6) == pytest.approx(0.36)

    def test_implied_price_requires_shares(self):
        with pytest.raises(ValidationError):
            calculate_implied_share_price(1_800e6, None)

    def test_implied_price_rejects_zero_shares(self):
        with pytest.raises(ValidationError):
            calculate_implied_share_price(1_800e6, 0)


# ---------------- DCF ----------------

class TestDcf:
    def test_discount_factors_end(self):
        dfs = discount_factors(0.10, 3)
        assert dfs[0] == pytest.approx(1 / 1.1)
        assert dfs[2] == pytest.approx(1 / 1.1 ** 3)

    def test_discount_factors_mid(self):
        dfs = discount_factors(0.10, 3, convention="mid")
        assert dfs[0] == pytest.approx(1 / 1.1 ** 0.5)

    def test_run_dcf_consistency(self):
        fcf = [100e6, 110e6, 121e6, 133e6, 146e6]
        from app.valuation.dcf import DcfInputs
        res = run_dcf(DcfInputs(
            fcf=fcf, wacc=0.09, cash=200e6, debt=400e6,
            shares_outstanding=1_000e6, current_share_price=1.0,
            terminal_growth=0.03,
        ))
        dfs = discount_factors(0.09, 5)
        assert res.pv_forecast_total == pytest.approx(sum(f * d for f, d in zip(fcf, dfs)))
        expected_tv = fcf[-1] * 1.03 / (0.09 - 0.03)
        assert res.terminal_value == pytest.approx(expected_tv)
        assert res.enterprise_value == pytest.approx(res.pv_forecast_total + res.pv_terminal_value)
        assert res.equity_value == pytest.approx(res.enterprise_value + 200e6 - 400e6)
        assert res.implied_share_price == pytest.approx(res.equity_value / 1_000e6)
        assert res.upside_downside == pytest.approx(res.implied_share_price / 1.0 - 1)

    def test_run_dcf_rejects_wacc_below_growth(self):
        from app.valuation.dcf import DcfInputs
        with pytest.raises(TerminalValueError):
            run_dcf(DcfInputs(fcf=[100e6], wacc=0.03, terminal_growth=0.04))

    def test_run_dcf_without_shares_returns_none_price(self):
        from app.valuation.dcf import DcfInputs
        res = run_dcf(DcfInputs(fcf=[100e6, 110e6], wacc=0.09, terminal_growth=0.03))
        assert res.implied_share_price is None  # never fabricate a price
        assert res.enterprise_value is not None


# ---------------- Beta ----------------

class TestBeta:
    def test_unlever_textbook(self):
        # 1.2 / (1 + 0.75*0.5) = 1.2/1.375 = 0.8727
        assert calculate_unlevered_beta(1.2, 0.5, 0.25) == pytest.approx(1.2 / 1.375)

    def test_relever_roundtrip(self):
        bl = calculate_relevered_beta(calculate_unlevered_beta(1.3, 0.7, 0.3), 0.7, 0.3)
        assert bl == pytest.approx(1.3)

    def test_unlever_no_debt_passthrough(self):
        assert calculate_unlevered_beta(1.1, 0.0, 0.21) == pytest.approx(1.1)

    def test_unlever_rejects_negative_de(self):
        with pytest.raises(ValidationError):
            calculate_unlevered_beta(1.2, -0.1, 0.25)

    def test_unlever_rejects_bad_tax(self):
        with pytest.raises(ValidationError):
            calculate_unlevered_beta(1.2, 0.5, 2.0)

    def test_regression_beta_recovers_true_beta(self):
        rng = np.random.default_rng(42)
        m = rng.normal(0.0004, 0.01, 500)
        y = 0.0002 + 1.4 * m + rng.normal(0, 0.005, 500)
        beta, alpha, r2 = regression_beta(y, m)
        assert 1.3 < beta < 1.5
        assert r2 > 0.8

    def test_regression_requires_min_obs(self):
        with pytest.raises(ValidationError):
            regression_beta(np.ones(5), np.ones(5))

    def test_aggregate_median_even(self):
        assert aggregate_beta([1.0, 1.2]) == pytest.approx(1.1)

    def test_aggregate_median_odd(self):
        assert aggregate_beta([1.0, 1.2, 0.8]) == pytest.approx(1.0)

    def test_aggregate_empty(self):
        with pytest.raises(ValidationError):
            aggregate_beta([])


# ---------------- Sensitivity ----------------

class TestSensitivity:
    def test_matrix_values(self):
        grid = calculate_sensitivity_matrix(lambda w, g: 100.0 / (w - g),
                                            [0.09, 0.10], [0.02, 0.03])
        assert grid.matrix[0][0] == pytest.approx(100 / 0.07)
        assert grid.matrix[1][1] == pytest.approx(100 / 0.07)

    def test_matrix_none_where_undefined(self):
        grid = calculate_sensitivity_matrix(
            lambda w, g: (_ for _ in ()).throw(ValueError("wacc<=g")) if g >= w else 1.0,
            [0.05], [0.02, 0.06],
        )
        assert grid.matrix[0][0] == 1.0
        assert grid.matrix[0][1] is None
        assert (0, 1) in grid.errors

    def test_tornado_swing(self):
        assert tornado_swing(100.0, 80.0, 130.0) == pytest.approx(30.0)

    def test_tornado_none_base(self):
        assert tornado_swing(None, 80.0, 130.0) is None

    def test_rejects_empty_grid(self):
        with pytest.raises(ValidationError):
            calculate_sensitivity_matrix(lambda a, b: 1.0, [], [1.0])
