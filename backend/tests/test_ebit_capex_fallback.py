"""EBIT + CapEx derivation regression tests.

Two more "missing drivers" failures found by the multi-ticker E2E run:

* JPM (bank) tags neither OperatingIncomeLoss nor any CapEx concept —
  ebit_margin AND capex_pct came back None and the forecast refused to run.
* JNJ stopped tagging OperatingIncomeLoss after FY2014 — recent periods had
  no EBIT even though EBT + interest expense were filed.

Both providers now reconstruct EBIT from pre-tax income (labelled), and
historical.analyze falls back to D&A intensity when CapEx is underivable —
mirroring the existing da_pct fix, never silently.
"""
from datetime import date

from app.data.providers.excel import _derive_derived
from app.data.providers.sec import SecEdgarProvider
from app.schemas.company import PeriodData
from app.schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from app.services.forecast import build_forecast
from app.services.historical import analyze

DRIVERS = ("revenue_growth", "ebit_margin", "da_pct", "capex_pct", "nwc_pct")


def _fact(year: int, val: float) -> dict:
    return {"cik": 1, "accn": "0000010-25-000001", "form": "10-K",
            "filed": f"{year + 1}-01-30", "start": f"{year}-01-01",
            "end": f"{year}-12-31", "val": val}


def _concept(*pairs: tuple[int, float]) -> dict:
    return {"units": {"USD": [_fact(y, v) for y, v in pairs]}}


# --------------------------------------------------------------------------
# SEC provider
# --------------------------------------------------------------------------

def test_sec_derives_ebit_with_interest_addback():
    """Industrial filer without OperatingIncomeLoss: EBIT = EBT + interest."""
    facts = {"facts": {"us-gaap": {
        "Revenues": _concept((2024, 100_000.0), (2025, 110_000.0)),
        # NOTE: no OperatingIncomeLoss
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            _concept((2024, 12_000.0), (2025, 13_500.0)),
        "InterestExpense": _concept((2024, 2_000.0), (2025, 2_200.0)),
        "NetIncomeLoss": _concept((2024, 9_000.0), (2025, 10_125.0)),
        "DepreciationDepletionAndAmortization": _concept((2024, 4_000.0), (2025, 4_400.0)),
        "PaymentsToAcquirePropertyPlantAndEquipment": _concept((2024, 5_000.0), (2025, 5_500.0)),
    }}}
    periods, warnings, _ = SecEdgarProvider().extract_periods(facts, "USD")
    p25 = next(p for p in periods if p.fiscal_year == 2025)
    ebit = p25.metrics["ebit"]
    assert ebit.value == 13_500.0 + 2_200.0
    assert ebit.source_type == SourceType.MODEL_CALCULATION
    assert "EBIT = EBT + Interest Expense" in ebit.note
    # driver derivable end to end
    analysis = analyze(periods)
    proposed = {a.key: a for a in analysis.proposed_assumptions}
    assert proposed["ebit_margin"].value is not None
    assert not any("missing ebit" in w for w in warnings)


def test_sec_bank_style_no_addback_when_interest_exceeds_revenue_share():
    """JPM-style: revenue reported NET of interest (interest > 20% of revenue)
    — EBIT ≈ EBT with no add-back; otherwise margins would be wildly overstated."""
    facts = {"facts": {"us-gaap": {
        "Revenues": _concept((2024, 177_556.0), (2025, 182_447.0)),
        # NOTE: no OperatingIncomeLoss (JPM tags none at all)
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            _concept((2024, 75_081.0), (2025, 72_595.0)),
        "InterestExpense": _concept((2024, 101_350.0)),
        "InterestExpenseOperating": _concept((2025, 97_898.0)),  # retag in FY25
        "NetIncomeLoss": _concept((2024, 58_471.0), (2025, 57_048.0)),
    }}}
    periods, warnings, _ = SecEdgarProvider().extract_periods(facts, "USD")
    p24 = next(p for p in periods if p.fiscal_year == 2024)
    p25 = next(p for p in periods if p.fiscal_year == 2025)
    # no add-back: EBIT ≈ EBT
    assert p24.value("ebit") == 75_081.0
    assert "net of interest" in p24.metrics["ebit"].note
    assert p25.value("ebit") == 72_595.0
    # retagged interest expense fills FY2025 via the concept union
    assert p25.value("interest_expense") == 97_898.0
    analysis = analyze(periods)
    proposed = {a.key: a for a in analysis.proposed_assumptions}
    assert proposed["ebit_margin"].value is not None


def test_sec_ebit_stale_operating_income_concept_skipped():
    """JNJ-style: OperatingIncomeLoss exists only for old years — recent
    periods must still derive EBIT, and the stale concept must not leak in."""
    facts = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax":
            _concept((2024, 88_821.0), (2025, 94_193.0)),
        "OperatingIncomeLoss": _concept((2013, 15_000.0)),  # stale, outside window
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            _concept((2024, 16_687.0), (2025, 32_581.0)),
        "InterestExpense": _concept((2024, 772.0)),
        "InterestExpenseNonoperating": _concept((2025, 971.0)),
        "NetIncomeLoss": _concept((2024, 14_000.0), (2025, 27_000.0)),
        "PaymentsToAcquirePropertyPlantAndEquipment": _concept((2024, 4_000.0), (2025, 4_300.0)),
    }}}
    periods, _, _ = SecEdgarProvider().extract_periods(facts, "USD")
    assert all(p.value("ebit") is not None for p in periods)
    p25 = next(p for p in periods if p.fiscal_year == 2025)
    # interest < 20% of revenue -> standard add-back
    assert p25.value("ebit") == 32_581.0 + 971.0
    assert p25.value("interest_expense") == 971.0  # union filled from Nonoperating


# --------------------------------------------------------------------------
# Excel provider (Mode A)
# --------------------------------------------------------------------------

def _sv(v: float, unit: Unit = Unit.CURRENCY) -> SourcedValue:
    return SourcedValue(value=v, unit=unit, source="test",
                        source_type=SourceType.USER_INPUT, status=ValueStatus.USER_DATA)


def test_excel_derives_ebit_when_workbook_lacks_ebit_row():
    """Workbook with EBT + interest but no EBIT row: EBIT reconstructed."""
    metrics = {
        "revenue": _sv(50_000.0),
        "ebt": _sv(6_000.0),
        "interest_expense": _sv(1_000.0),
        "net_income": _sv(4_500.0),
        "income_tax_expense": _sv(1_500.0),
        "da": _sv(2_000.0),
    }
    _derive_derived(metrics, 2025)
    ebit = metrics["ebit"]
    assert ebit.value == 7_000.0
    assert ebit.source_type == SourceType.MODEL_CALCULATION
    assert "no EBIT row" in ebit.note
    assert metrics["ebitda"].value == 9_000.0  # now derivable too


def test_excel_bank_style_no_addback():
    metrics = {"revenue": _sv(180_000.0), "ebt": _sv(70_000.0),
               "interest_expense": _sv(95_000.0)}  # 52.8% of revenue
    _derive_derived(metrics, 2025)
    assert metrics["ebit"].value == 70_000.0
    assert "interest exceeds 20%" in metrics["ebit"].note


# --------------------------------------------------------------------------
# historical.analyze belt-and-braces layer
# --------------------------------------------------------------------------

def _periods(rows: list[dict]) -> list[PeriodData]:
    out = []
    for i, row in enumerate(rows):
        y = 2022 + i
        out.append(PeriodData(period=f"FY{y}", fiscal_year=y, end_date=date(y, 12, 31),
                              period_type="annual", currency="USD", metrics={
                                  k: _sv(v) for k, v in row.items()}))
    return out


def test_analyze_derives_ebit_margin_from_ebt():
    """Periods carrying EBT + interest but no ebit metric (e.g. an upload that
    bypassed provider derivation): the driver must still come out."""
    periods = _periods([
        {"revenue": 100e6, "ebt": 14e6, "interest_expense": 2e6,
         "net_income": 10e6, "income_tax_expense": 4e6, "capex": 5e6, "da": 4e6},
        {"revenue": 108e6, "ebt": 15.5e6, "interest_expense": 2e6,
         "net_income": 11e6, "income_tax_expense": 4.5e6, "capex": 5e6, "da": 4e6},
        {"revenue": 116e6, "ebt": 17e6, "interest_expense": 2e6,
         "net_income": 12e6, "income_tax_expense": 5e6, "capex": 5e6, "da": 4e6},
    ])
    analysis = analyze(periods)
    proposed = {a.key: a for a in analysis.proposed_assumptions}
    assert proposed["ebit_margin"].value is not None
    # ratio rows carry the derivation label
    last_row = analysis.rows[-1]
    assert "EBT" in last_row.values["ebit_margin"].note
    # and the driver chain feeds a runnable forecast
    drivers = {k: proposed[k].value for k in DRIVERS}
    assert all(v is not None for v in drivers.values())
    fc = build_forecast(periods, drivers, years=5)
    assert len(fc.years) == 5


def test_capex_pct_falls_back_to_da_intensity():
    """JPM-style: no CapEx anywhere — proxy to D&A intensity, explicitly."""
    periods = _periods([
        {"revenue": 100e6, "ebit": 20e6, "ebt": 18e6, "interest_expense": 2e6,
         "net_income": 13.5e6, "income_tax_expense": 4.5e6, "da": 3e6},
        {"revenue": 108e6, "ebit": 22e6, "ebt": 20e6, "interest_expense": 2e6,
         "net_income": 15e6, "income_tax_expense": 5e6, "da": 3.2e6},
        {"revenue": 116e6, "ebit": 24e6, "ebt": 22e6, "interest_expense": 2e6,
         "net_income": 16.5e6, "income_tax_expense": 5.5e6, "da": 3.5e6},
    ])
    analysis = analyze(periods)
    proposed = {a.key: a for a in analysis.proposed_assumptions}
    capex = proposed["capex_pct"]
    da = proposed["da_pct"]
    assert capex.value is not None
    assert abs(capex.value - da.value) < 1e-9  # steady-state proxy CapEx ≈ D&A
    assert "NOT DERIVABLE" in capex.note
    drivers = {k: proposed[k].value for k in DRIVERS}
    assert all(v is not None for v in drivers.values())
    fc = build_forecast(periods, drivers, years=5)
    assert len(fc.years) == 5
