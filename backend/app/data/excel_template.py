"""Generates the downloadable Excel template for Mode A (own-company upload).

The template documents the expected fields and mirrors the heuristic parser:
clear sheet names, a label column, and period column headers it can detect.
"""
from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="1F2937")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=14)
NOTE_FONT = Font(italic=True, color="6B7280", size=10)
THIN = Side(style="thin", color="D1D5DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

YEARS = [date.today().year - 3, date.today().year - 2, date.today().year - 1]

INCOME_ROWS = [
    ("Revenue", 12_000_000, 13_800_000, 15_900_000),
    ("Cost of Goods Sold", -6_600_000, -7_452_000, -8_427_000),
    ("Gross Profit", 5_400_000, 6_348_000, 7_473_000),
    ("Operating Expenses", -3_600_000, -4_002_000, -4_452_000),
    ("EBIT / Operating Profit", 1_800_000, 2_346_000, 3_021_000),
    ("Interest Expense", -180_000, -171_000, -162_000),
    ("Income Before Tax (EBT)", 1_620_000, 2_175_000, 2_859_000),
    ("Income Tax Expense", -372_600, -500_250, -657_570),
    ("Net Income", 1_247_400, 1_674_750, 2_201_430),
    ("Depreciation & Amortization", 420_000, 460_000, 510_000),
]

CASHFLOW_ROWS = [
    ("Operating Cash Flow", 2_050_000, 2_640_000, 3_300_000),
    ("Depreciation & Amortization", 420_000, 460_000, 510_000),
    ("Capital Expenditure", -600_000, -660_000, -740_000),
    ("Change in Net Working Capital", -150_000, -180_000, -210_000),
]

BALANCE_ROWS = [
    ("Cash & Cash Equivalents", 1_500_000, 1_780_000, 2_120_000),
    ("Accounts Receivable", 1_100_000, 1_250_000, 1_430_000),
    ("Inventory", 900_000, 980_000, 1_090_000),
    ("Total Current Assets", 4_000_000, 4_500_000, 5_150_000),
    ("Total Assets", 9_500_000, 10_600_000, 11_900_000),
    ("Accounts Payable", 750_000, 810_000, 890_000),
    ("Total Current Liabilities", 1_600_000, 1_720_000, 1_860_000),
    ("Short-Term Debt", 250_000, 250_000, 250_000),
    ("Long-Term Debt", 2_750_000, 2_500_000, 2_250_000),
    ("Total Liabilities", 5_600_000, 5_700_000, 5_700_000),
    ("Shareholders' Equity", 3_900_000, 4_900_000, 6_200_000),
    ("Shares Outstanding", 5_000_000, 5_000_000, 5_000_000),
]

DEBT_ROWS = [
    ("Term Loan A", 25_000_000, 0.055),
    ("Revolver", 15_000_000, 0.060),
]

ASSUMPTION_ROWS = [
    ("Revenue Growth", 0.08, "Applied to all forecast years unless overridden"),
    ("EBIT Margin", 0.19, "Target operating margin"),
    ("Tax Rate", 0.25, "Effective rate used in NOPAT"),
    ("D&A / Revenue", 0.032, "Percentage of revenue"),
    ("CapEx / Revenue", 0.045, "Percentage of revenue"),
    ("NWC / Revenue", 0.02, "Incremental NWC as % of revenue growth"),
    ("Terminal Growth", 0.03, "Perpetuity growth; must be below WACC"),
    ("Exit Multiple", 11.0, "EV/EBITDA exit multiple"),
    ("Share Price", 24.50, "Current price if private markets exist; else leave blank"),
    ("Risk-Free Rate", 0.038, "e.g. 10Y treasury"),
    ("Market Risk Premium", 0.05, "Equity risk premium"),
    ("Beta", 1.1, "Leave blank to estimate from comparables"),
    ("Target D/E", 0.4, "Target debt/equity for relevering beta"),
]


def _style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center")


def _write_period_sheet(ws, title: str, rows: list[tuple], unit_note: str) -> None:
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("INSTRUCTIONS: keep the row labels (column A) — the ingester matches them by keyword. "
                "Replace the sample numbers with your own values, one column per fiscal year. "
                "Amounts in absolute currency units (e.g. 1,200,000 not 1.2M).")
    ws["A2"].font = NOTE_FONT
    ws["A3"] = unit_note
    ws["A3"].font = NOTE_FONT

    header_row = 5
    ws.cell(row=header_row, column=1, value="Line Item")
    for i, y in enumerate(YEARS):
        ws.cell(row=header_row, column=2 + i, value=f"FY{y}")
    _style_header(ws, header_row, 1 + len(YEARS))

    for r, row in enumerate(rows, start=header_row + 1):
        ws.cell(row=r, column=1, value=row[0]).border = BORDER
        for i, v in enumerate(row[1:]):
            cell = ws.cell(row=r, column=2 + i, value=v)
            cell.number_format = "#,##0;(#,##0)"
            cell.border = BORDER
    ws.column_dimensions["A"].width = 42
    for i in range(len(YEARS)):
        ws.column_dimensions[get_column_letter(2 + i)].width = 16


def build_template() -> io.BytesIO:
    wb = Workbook()

    # Instructions
    ws = wb.active
    ws.title = "README"
    lines = [
        "DCF labs — Company Financials Template",
        "=" * 46,
        "",
        "Fill in your own numbers. Delete sample values — do not leave them in.",
        "",
        "Sheets:",
        "  Income Statement   required — revenue, EBIT, net income, D&A, taxes",
        "  Cash Flow          required — operating cash flow, CapEx, change in NWC",
        "  Balance Sheet      required for the equity bridge — cash, debt, shares",
        "  Assumptions        optional — your own drivers (growth, margins, WACC inputs)",
        "  Debt Schedule      optional — individual instruments for weighted cost of debt",
        "",
        "Rules:",
        "  * One column per fiscal year with headers like FY2023, FY2024, FY2025.",
        "  * Row labels in column A; the ingester matches them by keyword, so use standard names.",
        "  * Amounts in absolute currency units. Add 'in thousands/millions' in A3 if you scale them",
        "    (e.g. 'All figures in thousands').",
        "  * Negative numbers for outflows (shown in parentheses is fine).",
        "  * Never invent numbers to fill gaps — leave blanks. Missing data is reported, not guessed.",
        "",
        "After upload you will see a Data Review table where every mapping can be corrected.",
    ]
    for i, line in enumerate(lines, start=1):
        ws.cell(row=i, column=1, value=line)
    ws.column_dimensions["A"].width = 100
    ws["A1"].font = TITLE_FONT

    _write_period_sheet(wb.create_sheet("Income Statement"), "Income Statement", INCOME_ROWS,
                        "All figures in absolute currency units (USD).")
    _write_period_sheet(wb.create_sheet("Cash Flow"), "Cash Flow Statement", CASHFLOW_ROWS,
                        "CapEx and change in NWC as positive outflows if shown with a minus sign — keep the sign convention you use.")
    _write_period_sheet(wb.create_sheet("Balance Sheet"), "Balance Sheet", BALANCE_ROWS,
                        "Point-in-time balances at fiscal year end.")

    # Assumptions
    ws = wb.create_sheet("Assumptions")
    ws["A1"] = "Assumptions (optional)"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "Enter percentages as decimals (0.08 = 8%). Leave blank to let the model estimate from history."
    ws["A2"].font = NOTE_FONT
    ws.cell(row=4, column=1, value="Assumption")
    ws.cell(row=4, column=2, value="Value")
    ws.cell(row=4, column=3, value="Notes")
    _style_header(ws, 4, 3)
    for r, (label, value, note) in enumerate(ASSUMPTION_ROWS, start=5):
        ws.cell(row=r, column=1, value=label).border = BORDER
        c = ws.cell(row=r, column=2, value=value)
        c.border = BORDER
        c.number_format = "0.00%" if value < 1 else "#,##0.00"
        ws.cell(row=r, column=3, value=note).border = BORDER
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 60

    # Debt schedule
    ws = wb.create_sheet("Debt Schedule")
    ws["A1"] = "Debt Schedule (optional)"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "Each instrument's amount and annual interest rate. Used for the weighted cost of debt."
    ws["A2"].font = NOTE_FONT
    ws.cell(row=4, column=1, value="Instrument")
    ws.cell(row=4, column=2, value="Amount")
    ws.cell(row=4, column=3, value="Rate")
    _style_header(ws, 4, 3)
    for r, (name, amt, rate) in enumerate(DEBT_ROWS, start=5):
        ws.cell(row=r, column=1, value=name).border = BORDER
        ws.cell(row=r, column=2, value=amt).number_format = "#,##0"
        ws.cell(row=r, column=3, value=rate).number_format = "0.00%"
        for c in range(1, 4):
            ws.cell(row=r, column=c).border = BORDER
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 12

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
