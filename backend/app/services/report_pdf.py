"""Report PDF export — a printable version of the same deterministic report.

The PDF is rendered from the persisted `ReportDoc` (title, sections, tables and
disclaimer); nothing is recomputed or re-narrated here, so the exported document
always matches what the Report page shows.
"""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)

from ..schemas.valuation import ValuationView

# printable palette (no dark backgrounds — this is a document, not a screen)
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4b5563")
RULE = colors.HexColor("#d1d5db")
HEAD_BG = colors.HexColor("#f3f4f6")
ACCENT = colors.HexColor("#1d4ed8")
WARN_BG = colors.HexColor("#fef3c7")

_PAGE_W, _PAGE_H = A4
_MARGIN = 18 * mm
_CONTENT_W = _PAGE_W - 2 * _MARGIN
# tables wider than this get their own landscape page instead of wrapping
# numbers mid-digit in a portrait column
_WIDE_TABLE_COLS = 8
_LAND_CONTENT_W = _PAGE_H - 2 * _MARGIN

# Characters the standard PDF fonts (WinAnsi) cannot draw are transliterated
# instead of silently rendering as black boxes.
_REPL = {
    "\u2192": "->", "\u2190": "<-", "\u2194": "<->", "\u20b9": "Rs ",
    "\u2248": "~", "\u2264": "<=", "\u2265": ">=", "\u2260": "!=",
    "\u2713": "yes", "\u2717": "no", "\u2212": "-", "\u2013": "-",
    "\u2014": "-", "\u2026": "...", "\u00d7": "x", "\u00b1": "+/-",
    "\u20ac": "EUR ", "\u00a3": "GBP ", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
}


def _safe(text: object) -> str:
    """Transliterate to CP1252 and escape for reportlab's mini-markup."""
    s = "" if text is None else str(text)
    for bad, good in _REPL.items():
        s = s.replace(bad, good)
    out = []
    for ch in s:
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            out.append("?")
        else:
            out.append(ch)
    s = "".join(out)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(x: float | None, cur: str = "") -> str:
    if x is None:
        return "n/a"
    return f"{'-' if x < 0 else ''}{cur}{abs(x):,.2f}"


def _money0(x: float | None, cur: str = "") -> str:
    if x is None:
        return "n/a"
    return f"{'-' if x < 0 else ''}{cur}{abs(x):,.0f}"


def _pct(x: float | None, digits: int = 2) -> str:
    return f"{x * 100:.{digits}f}%" if x is not None else "n/a"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "kicker": ParagraphStyle(
            "kicker", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.5,
            leading=10, textColor=ACCENT, spaceAfter=6,
        ),
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=17,
            leading=21, textColor=INK, alignment=0, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=9.5,
            leading=13, textColor=MUTED, spaceAfter=6,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base["Normal"], fontName="Helvetica", fontSize=7.5,
            leading=10, textColor=MUTED,
        ),
        # headings keep their following label/paragraph on the same page
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11,
            leading=14, textColor=INK, spaceBefore=10, spaceAfter=3, keepWithNext=1,
        ),
        "kind": ParagraphStyle(
            "kind", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6.2,
            leading=8, textColor=MUTED, keepWithNext=1,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica", fontSize=8.8,
            leading=12.4, textColor=INK, spaceAfter=4,
        ),
        "body_keep": ParagraphStyle(
            "body_keep", parent=base["Normal"], fontName="Helvetica", fontSize=8.8,
            leading=12.4, textColor=INK, spaceAfter=4, keepWithNext=1,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"], fontName="Helvetica", fontSize=8.8,
            leading=12.4, textColor=INK, leftIndent=10, bulletIndent=2, spaceAfter=2,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontName="Helvetica", fontSize=7.4,
            leading=9.4, textColor=INK,
        ),
        "cell_head": ParagraphStyle(
            "cell_head", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6.6,
            leading=8.6, textColor=MUTED,
        ),
        # compact variants for landscape tables (>8 columns)
        "cell_s": ParagraphStyle(
            "cell_s", parent=base["Normal"], fontName="Helvetica", fontSize=6.4,
            leading=8.2, textColor=INK,
        ),
        "cell_head_s": ParagraphStyle(
            "cell_head_s", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6.0,
            leading=7.8, textColor=MUTED,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontName="Helvetica", fontSize=7,
            leading=9, textColor=MUTED,
        ),
        "value": ParagraphStyle(
            "value", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9.4,
            leading=12, textColor=INK,
        ),
        "note": ParagraphStyle(
            "note", parent=base["Normal"], fontName="Helvetica-Oblique", fontSize=7.2,
            leading=10, textColor=MUTED,
        ),
    }


def _blocks(body: str) -> list[tuple[str, list[str]]]:
    """Split narrative text into paragraphs / bullet groups (same rules as the UI)."""
    out: list[tuple[str, list[str]]] = []
    last_bullet = False
    for raw in (body or "").split("\n"):
        text = raw.strip()
        if not text:
            last_bullet = False
            continue
        if text.startswith(("- ", "\u2022 ")):
            item = text[2:].strip()
            if last_bullet and out and out[-1][0] == "ul":
                out[-1][1].append(item)
            else:
                out.append(("ul", [item]))
            last_bullet = True
        elif last_bullet and out and out[-1][0] == "ul" and raw.startswith("  "):
            out[-1][1][-1] += " " + text
        else:
            if out and out[-1][0] == "p" and not last_bullet:
                out[-1][1].append(text)
            else:
                out.append(("p", [text]))
            last_bullet = False
    return out


def _verdict_table(view: ValuationView, st: dict[str, ParagraphStyle]) -> Table:
    s = view.summary
    cur = view.company.currency or ""
    pairs = [
        ("Our estimate / share", _money(s.implied_share_price, cur)),
        ("Market price", _money(s.current_share_price, cur)),
        ("Difference vs market", _pct(s.upside_downside, 1)),
        ("WACC (discount rate)", _pct(s.wacc)),
        ("Enterprise value", _money0(s.enterprise_value, cur)),
        ("Equity value", _money0(s.equity_value, cur)),
    ]
    data = [[Paragraph(_safe(k), st["label"]), Paragraph(_safe(v), st["value"])] for k, v in pairs]
    left, right = data[:3], data[3:]
    rows = [[a[0], a[1], b[0], b[1]] for a, b in zip(left, right)]
    widths = [_CONTENT_W * f for f in (0.24, 0.26, 0.24, 0.26)]
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEAD_BG),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _column_widths(columns: list, rows: list, total: float = _CONTENT_W) -> list[float]:
    """Share the page width by content length so short-token columns such as
    SOURCE_TYPE (MODEL_ASSUMPTION) or long money values do not wrap mid-word."""
    n = max(len(columns), 1)
    if n == 1:
        return [total]
    weights = []
    for i, c in enumerate(columns):
        longest = len(str(c or ""))
        for row in rows:
            if i < len(row) and row[i] is not None:
                longest = max(longest, len(str(row[i])))
        # label column gets a floor; no column monopolises the table
        weights.append(min(max(longest, 10 if i == 0 else 7), 46))
    scale = float(sum(weights)) or 1.0
    return [total * w / scale for w in weights]


def _cell_text(value: object) -> str:
    """Cell text that breaks at a sensible boundary (SOURCE_TYPE enums such as
    MODEL_ASSUMPTION) instead of wrapping mid-word in a narrow column."""
    s = "" if value is None else str(value)
    if " " not in s and len(s) > 13:
        for sep in ("_", "/", "-"):
            head, found, tail = s.partition(sep)
            if found and 0 < len(head) <= 13 and 0 < len(tail) <= 13:
                return _safe(head + found) + "<br/>" + _safe(tail)
    return _safe(s)


def _is_wide(section) -> bool:
    table = getattr(section, "table", None)
    return bool(table and table.get("rows")
                and len(table.get("columns") or []) > _WIDE_TABLE_COLS)


def _data_table(columns: list, rows: list, st: dict[str, ParagraphStyle],
                compact: bool = False) -> Table:
    n = max(len(columns), 1)
    width = _LAND_CONTENT_W if compact else _CONTENT_W
    widths = _column_widths(columns, rows, width)
    head = [Paragraph(_safe(c), st["cell_head_s" if compact else "cell_head"]) for c in columns]
    body = [
        [Paragraph(_cell_text(cell), st["cell_s" if compact else "cell"]) for cell in row]
        for row in rows
    ]
    pad = 3 if compact else 5
    t = Table([head] + body, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), pad),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _section_block(section, st: dict[str, ParagraphStyle]):
    flow = []
    kind = getattr(section, "kind", "") or ""
    heading = getattr(section, "heading", "")
    flow.append(Paragraph(_safe(heading), st["h2"]))
    if kind:
        flow.append(Paragraph(_safe(kind), st["kind"]))
        flow.append(Spacer(1, 4))
    for kind_block, items in _blocks(getattr(section, "body", "") or ""):
        if kind_block == "ul":
            for item in items:
                flow.append(Paragraph(_safe(item), st["bullet"], bulletText="\u2022"))
        else:
            for item in items:
                # a short lead-in ("INTERPRETATION (…):") should not be stranded
                # at the foot of a page away from its list
                lead_in = item.rstrip().endswith(":") and len(item) <= 90
                flow.append(Paragraph(_safe(item), st["body_keep" if lead_in else "body"]))
    table = getattr(section, "table", None)
    if table and table.get("rows"):
        flow.append(Spacer(1, 4))
        flow.append(_data_table(table.get("columns") or [], table.get("rows") or [], st,
                                compact=_is_wide(section)))
        flow.append(Spacer(1, 2))
    return flow


def render_report_pdf(view: ValuationView) -> bytes:
    """Render `view.report` as a PDF byte string. Raises ValueError without a report."""
    report = view.report
    if report is None:
        raise ValueError("Valuation has no report to export")

    st = _styles()
    company = view.company
    buf = io.BytesIO()

    def _footer(canvas, doc_):
        # page size follows the active template (portrait or landscape)
        page_w, _ = getattr(canvas, "_pagesize", A4)
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(_MARGIN, 14 * mm, page_w - _MARGIN, 14 * mm)
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(_MARGIN, 10 * mm, "DCF-LABS - model-based valuation. Not investment advice.")
        canvas.drawRightString(page_w - _MARGIN, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=_MARGIN, bottomMargin=20 * mm,
        title=f"{company.name} - valuation report", author="DCF labs",
        subject=report.title,
    )
    doc.addPageTemplates([
        PageTemplate(
            id="portrait",
            frames=[Frame(_MARGIN, 20 * mm, _CONTENT_W, _PAGE_H - 20 * mm - _MARGIN, id="pf")],
            onPage=_footer, pagesize=A4,
        ),
        PageTemplate(
            id="landscape",
            frames=[Frame(_MARGIN, 20 * mm, _LAND_CONTENT_W, _PAGE_W - 20 * mm - _MARGIN, id="lf")],
            onPage=_footer, pagesize=landscape(A4),
        ),
    ])

    story: list = []
    story.append(Paragraph("DCF LABS - VALUATION REPORT", st["kicker"]))
    story.append(Paragraph(_safe(report.title), st["title"]))
    if report.subtitle:
        story.append(Paragraph(_safe(report.subtitle), st["subtitle"]))

    bits = [company.name]
    if company.ticker:
        bits.append(company.ticker)
    if company.currency:
        bits.append(company.currency)
    bits.append(f"audit {report.audit_status.value if hasattr(report.audit_status, 'value') else report.audit_status}")
    if report.generated_at:
        bits.append(datetime.fromtimestamp(report.generated_at.timestamp()).strftime("%d %b %Y %H:%M"))
    story.append(Paragraph(_safe("  |  ".join(str(b) for b in bits)), st["meta"]))
    story.append(Spacer(1, 10))
    story.append(_verdict_table(view, st))

    if view.summary.status == "blocked" and view.summary.blocked_reasons:
        story.append(Spacer(1, 8))
        reason = " ".join(f"- {r}" for r in view.summary.blocked_reasons)
        warn = Table(
            [[Paragraph(_safe(f"Blocked by audit: {reason}"), st["body"])]],
            colWidths=[_CONTENT_W],
        )
        warn.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d97706")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(warn)

    for section in report.sections:
        if _is_wide(section):
            # heading, body and the wide table share one landscape page
            story += [NextPageTemplate("landscape"), PageBreak()]
        else:
            story.append(Spacer(1, 6))
        story.extend(_section_block(section, st))
        if _is_wide(section):
            story += [NextPageTemplate("portrait"), PageBreak()]

    story.append(Spacer(1, 14))
    story.append(_data_table(
        ["Provenance"],
        [["Every figure in this report is labelled FACT, CALCULATION, ASSUMPTION, USER OVERRIDE, "
          "MODEL ESTIMATE or NARRATIVE. The full machine-readable provenance (JSON) is exported "
          "from the Report page."]],
        st,
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(_safe(report.disclaimer), st["note"]))

    doc.build(story)
    return buf.getvalue()
