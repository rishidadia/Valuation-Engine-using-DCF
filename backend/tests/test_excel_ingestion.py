"""Excel ingestion tests: template round-trip + heuristic layout detection.

Proves the ingester adapts to layouts it has never seen instead of assuming
a fixed template.
"""
import pytest
from openpyxl import Workbook

from app.core.errors import ExcelValidationError
from app.data.excel_template import build_template
from app.data.providers.excel import ExcelProvider


@pytest.fixture
def provider() -> ExcelProvider:
    return ExcelProvider()


def _save(wb: Workbook, path):
    wb.save(path)
    return path


def test_template_ingests(provider, tmp_path):
    path = tmp_path / "template.xlsx"
    path.write_bytes(build_template().getvalue())
    import asyncio
    payload = asyncio.run(provider.fetch(path, original_name="template.xlsx",
                                          company_name="Acme Manufacturing"))
    assert payload.company.name == "Acme Manufacturing"
    assert payload.company.is_public is False
    years = [p.fiscal_year for p in payload.periods]
    assert len(years) == 3
    latest = payload.periods[-1]
    assert latest.value("revenue") is not None
    assert latest.value("ebit") is not None
    assert latest.value("cash") is not None
    assert latest.value("total_debt") is not None
    assert latest.value("shares_outstanding") is not None
    # provenance is cell-level
    rev = latest.metrics["revenue"]
    assert rev.source_type.value == "UPLOADED_EXCEL"
    assert rev.cell_ref and rev.cell_ref.startswith("Income Statement!")
    # derived EBITDA is labelled as a calculation
    assert "ebitda" in latest.metrics
    assert latest.metrics["ebitda"].source_type.value == "MODEL_CALCULATION"
    # assumptions sheet parsed
    assert provider.assumption_values.get("tax_rate") == pytest.approx(0.25)
    assert provider.assumption_values.get("terminal_growth") == pytest.approx(0.03)
    # debt schedule parsed
    assert len(provider.debt_instruments) == 2
    assert provider.debt_instruments[0]["rate"] == pytest.approx(0.055)


def test_unknown_layout_detected(provider, tmp_path):
    """Sheet names/labels the template never used still map correctly."""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "P&L Detail"
    ws1["A1"] = "Acme Corp — in thousands"
    ws1["A3"] = "Line"
    ws1["B3"] = "Dec-2023"
    ws1["C3"] = "Dec-2024"
    ws1["D3"] = "Dec-2025"
    rows = [
        ("Total Revenue", 8000, 9200, 10580),
        ("Cost of Revenue", -4400, -4968, -5613),
        ("Gross Profit", 3600, 4232, 4967),
        ("Operating Income", 1200, 1472, 1789),
        ("Net Income", 780, 962, 1180),
    ]
    for i, (label, *vals) in enumerate(rows, start=4):
        ws1.cell(row=i, column=1, value=label)
        for j, v in enumerate(vals):
            ws1.cell(row=i, column=2 + j, value=v)

    ws2 = wb.create_sheet("SOFP")
    ws2["A1"] = "Statement of Financial Position"
    ws2["A3"] = "Line"
    ws2["B3"] = "Dec-2024"
    ws2["C3"] = "Dec-2025"
    bs_rows = [
        ("Cash and Cash Equivalents", 1500, 1900),
        ("Total Assets", 12000, 13400),
        ("Long-Term Debt", 3000, 2800),
        ("Total Equity", 5200, 6100),
    ]
    for i, (label, *vals) in enumerate(bs_rows, start=4):
        ws2.cell(row=i, column=1, value=label)
        for j, v in enumerate(vals):
            ws2.cell(row=i, column=2 + j, value=v)

    path = _save(wb, tmp_path / "weird.xlsx")
    import asyncio
    payload = asyncio.run(provider.fetch(path, original_name="weird.xlsx"))
    years = sorted(p.fiscal_year for p in payload.periods)
    assert years == [2023, 2024, 2025]  # P&L covers 3 years, balance sheet 2
    p25 = next(p for p in payload.periods if p.fiscal_year == 2025)
    # unit scale: "in thousands" detected -> values scaled to absolute units
    assert p25.value("revenue") == pytest.approx(10580 * 1000)
    assert p25.value("ebit") == pytest.approx(1789 * 1000)
    assert p25.value("cash") == pytest.approx(1900 * 1000)
    assert p25.value("total_debt") == pytest.approx(2800 * 1000)


def test_parenthesised_negative_numbers(provider, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Income Statement"
    ws["A1"] = "Figures"
    ws["B1"] = "FY2024"
    ws["C1"] = "FY2025"
    ws["A2"] = "Revenue"
    ws["B2"] = "1,000"
    ws["C2"] = "1,200"
    ws["A3"] = "Operating Income"
    ws["B3"] = "(200)"
    ws["C3"] = "150"
    path = _save(wb, tmp_path / "neg.xlsx")
    import asyncio
    payload = asyncio.run(provider.fetch(path, original_name="neg.xlsx"))
    p = payload.periods[-1]
    assert p.value("revenue") == pytest.approx(1200)
    assert p.value("ebit") == pytest.approx(150)
    assert payload.periods[0].value("ebit") == pytest.approx(-200)


def test_rejects_wrong_extension(provider, tmp_path):
    bad = tmp_path / "book.csv"
    bad.write_text("a,b\n1,2")
    with pytest.raises(ExcelValidationError) as ei:
        provider.validate_file(bad, "book.csv")
    assert ".xlsx" in str(ei.value.detail)


def test_rejects_oversized_file(provider, tmp_path):
    big = tmp_path / "big.xlsx"
    big.write_bytes(b"0" * (11 * 1024 * 1024))
    with pytest.raises(ExcelValidationError) as ei:
        provider.validate_file(big, "big.xlsx")
    assert "too large" in str(ei.value.detail)


def test_rejects_garbage_bytes(provider, tmp_path):
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"this is not a zip file")
    with pytest.raises(ExcelValidationError):
        import asyncio
        asyncio.run(provider.fetch(junk, original_name="junk.xlsx"))


def test_empty_workbook_reports_missing_not_fabricated(provider, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Random Notes"
    ws["A1"] = "hello world"
    path = _save(wb, tmp_path / "empty.xlsx")
    import asyncio
    with pytest.raises(ExcelValidationError) as ei:
        asyncio.run(provider.fetch(path, original_name="empty.xlsx"))
    assert "No financial statement rows" in str(ei.value.detail)


def test_percentage_assumptions_normalised(provider):
    """8, 8.00% and 0.08 must all mean 8% (not 800%)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Assumptions"
    rows = [
        ("Revenue Growth", 8),          # percentage points
        ("EBIT Margin", "8.00%"),       # explicit percent string
        ("Terminal Growth", 0.08),      # already a decimal
        ("Tax Rate", 21),               # 21% typed as 21
        ("Beta", 1.2),                  # ratio, must NOT be divided
        ("Exit Multiple", 10.0),        # multiple, must NOT be divided
        ("Forecast Years", 7),          # count, must NOT be divided
        ("Target D/E", 0.4),            # ratio >0 but <1, must stay
    ]
    for i, (label, value) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=value)

    parsed = provider._parse_assumptions(ws)

    assert parsed["revenue_growth"] == pytest.approx(0.08)
    assert parsed["ebit_margin"] == pytest.approx(0.08)
    assert parsed["terminal_growth"] == pytest.approx(0.08)
    assert parsed["tax_rate"] == pytest.approx(0.21)
    assert parsed["beta"] == pytest.approx(1.2)
    assert parsed["exit_multiple"] == pytest.approx(10.0)
    assert parsed["forecast_years"] == pytest.approx(7.0)
    assert parsed["target_de"] == pytest.approx(0.4)


# ---------------- currency & fiscal year ----------------

from datetime import date  # noqa: E402


def _simple_statement_book() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Income Statement"
    ws["A1"] = "Statement"
    ws["B1"] = "FY2024"
    ws["C1"] = "FY2025"
    for i, (label, v24, v25) in enumerate([
        ("Revenue", 1000, 1100),
        ("Operating Income", 180, 200),
        ("Net Income", 130, 145),
    ], start=2):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=v24)
        ws.cell(row=i, column=3, value=v25)
    return wb


def test_currency_and_fiscal_year_end_applied(provider, tmp_path):
    path = _save(_simple_statement_book(), tmp_path / "eur.xlsx")
    import asyncio
    payload = asyncio.run(provider.fetch(
        path, original_name="eur.xlsx", currency="eur", fiscal_year_end="09-30"))

    assert payload.company.currency == "EUR"
    assert {p.currency for p in payload.periods} == {"EUR"}
    assert all(p.end_date.month == 9 and p.end_date.day == 30 for p in payload.periods)
    assert payload.periods[-1].end_date == date(2025, 9, 30)
    assert any("US-dollar based" in w for w in payload.warnings)
    assert any("Fiscal year end" in w for w in payload.warnings)


def test_currency_detected_from_workbook_header(provider, tmp_path):
    wb = _simple_statement_book()
    wb.active["A3"] = "All figures in thousands of GBP"
    path = _save(wb, tmp_path / "gbp.xlsx")
    import asyncio
    payload = asyncio.run(provider.fetch(path, original_name="gbp.xlsx"))
    assert payload.company.currency == "GBP"
    assert payload.periods[-1].currency == "GBP"


def test_invalid_currency_rejected(provider, tmp_path):
    path = _save(_simple_statement_book(), tmp_path / "bad.xlsx")
    import asyncio
    with pytest.raises(ExcelValidationError) as ei:
        asyncio.run(provider.fetch(path, original_name="bad.xlsx", currency="EUROS"))
    assert "Invalid currency" in ei.value.detail


def test_invalid_fiscal_year_end_rejected(provider, tmp_path):
    path = _save(_simple_statement_book(), tmp_path / "bad2.xlsx")
    import asyncio
    with pytest.raises(ExcelValidationError) as ei:
        asyncio.run(provider.fetch(path, original_name="bad2.xlsx", fiscal_year_end="13-45"))
    assert "Invalid fiscal year end" in ei.value.detail
