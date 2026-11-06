"""Report PDF export — deterministic, offline, no network or LLM involvement."""
from datetime import datetime, timezone

import pytest

from app.schemas.common import CheckStatus
from app.schemas.company import CompanyInfo
from app.schemas.valuation import (
    ReportDoc, ReportSection, ValuationSummary, ValuationView,
)
from app.services.report_pdf import _blocks, _safe, render_report_pdf


def _view(**summary_overrides) -> ValuationView:
    company = CompanyInfo(name="Test Industries Ltd", ticker="TEST", currency="INR")
    report = ReportDoc(
        title="Valuation Report - Test Industries Ltd",
        subtitle="Is it valued properly?",
        generated_at=datetime.now(timezone.utc),
        audit_status=CheckStatus.PASS,
        sections=[
            ReportSection(
                heading="1. Bottom Line",
                kind="CALCULATION",
                body="OVERVALUED vs our model.\n\n- first bullet\n- second bullet\n  continued",
            ),
            ReportSection(
                heading="2. Sensitivity",
                kind="FACT",
                body="Grid of implied values:",
                table={"columns": ["WACC", "Value"], "rows": [["11%", 1234.5], ["12%", None]]},
            ),
        ],
    )
    summary = ValuationSummary(
        **{
            "id": "v1",
            "company": company,
            "implied_share_price": 1234.5,
            "current_share_price": 1500.0,
            "upside_downside": -0.177,
            "enterprise_value": 1.5e10,
            "equity_value": 1.6e10,
            "wacc": 0.1234,
            "terminal_growth": 0.04,
            "audit_status": CheckStatus.PASS,
        }
        | summary_overrides
    )
    return ValuationView(summary=summary, company=company, report=report)


def test_pdf_is_a_valid_pdf_document():
    pdf = render_report_pdf(_view())
    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 2000


def test_pdf_requires_a_report():
    view = _view()
    view.report = None
    with pytest.raises(ValueError):
        render_report_pdf(view)


def test_special_characters_are_transliterated_for_the_pdf_fonts():
    # Standard PDF fonts cannot draw these; they must not become black boxes.
    assert _safe("\u20b91,234 \u2192 12%") == "Rs 1,234 -&gt; 12%"
    assert _safe("caf\u00e9 n\u00e4ive") == "caf\u00e9 n\u00e4ive"
    assert _safe("\u2713 pass") == "yes pass"
    assert _safe("A & B < C") == "A &amp; B &lt; C"


def test_bullets_and_paragraphs_are_split():
    blocks = _blocks("Lead in.\n\n- one\n- two\n  continued\nParagraph after.")
    assert blocks[0] == ("p", ["Lead in."])
    assert blocks[1] == ("ul", ["one", "two continued"])
    assert blocks[2] == ("p", ["Paragraph after."])


def test_blocked_valuation_still_renders():
    view = _view(status="blocked", blocked_reasons=["Revenue is missing for FY2026"])
    pdf = render_report_pdf(view)
    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")
