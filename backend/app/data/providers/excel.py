"""ExcelProvider — ingests user-uploaded .xlsx financial workbooks.

Design principles:
  * Never assume a fixed layout. Sheets, rows and period columns are detected.
  * Never fabricate. Ambiguous mappings are flagged for user review.
  * Keep cell-level provenance ("Income Statement!C7") for every value.
  * openpyxl reads values only — uploaded files are never executed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from ...core.config import settings
from ...core.errors import ExcelValidationError
from ...schemas.common import SourceType, SourcedValue, Unit, ValueStatus
from ...schemas.company import CompanyInfo, MappingNote, PeriodData
from .base import DataProvider, ProviderPayload, today

# ---------------------------------------------------------------------------
# Label patterns: canonical key -> ordered (regex, confidence)
# First confident match wins; ambiguous matches are surfaced to the user.
# ---------------------------------------------------------------------------

PATTERNS: list[tuple[str, list[tuple[str, float]]]] = [
    ("revenue", [
        (r"^\s*total\s+(net\s+)?revenue\s*$", 0.98),
        (r"^\s*revenue\s*(\(\w+\))?\s*$", 0.95),
        (r"^\s*total\s+net\s+sales\s*$", 0.93),
        (r"^\s*net\s+sales\s*(\(\w+\))?\s*$", 0.90),
        (r"^\s*(net\s+)?revenue\b", 0.85),
        (r"^\s*sales\b", 0.75),
        (r"^\s*total\s+sales\s*$", 0.80),
    ]),
    ("cogs", [
        (r"^\s*(total\s+)?cost\s+of\s+(goods\s+sold|revenue|sales|products)\b", 0.95),
        (r"^\s*cogs\s*$", 0.92),
        (r"^\s*cost\s+of\s+revenue\b", 0.90),
    ]),
    ("gross_profit", [(r"^\s*gross\s+(profit|margin)\s*$", 0.95)]),
    ("operating_expenses", [
        (r"^\s*(total\s+)?operating\s+expenses\s*$", 0.95),
        (r"^\s*sg\s*&?\s*a\b", 0.70),
        (r"^\s*selling[,\s]+general\b", 0.70),
    ]),
    ("ebit", [
        (r"^\s*(operating\s+profit|operating\s+income|ebit)(\s*[/|]\s*(operating\s+profit|operating\s+income|ebit))?\s*(\(\w+\))?\s*$", 0.96),
        (r"^\s*income\s+from\s+operations\s*$", 0.93),
        (r"^\s*operating\s+(income|profit)\b", 0.85),
    ]),
    ("interest_expense", [(r"^\s*(total\s+)?interest\s+expense\s*$", 0.95),
                          (r"^\s*interest\s+expense\b", 0.85)]),
    ("ebt", [(r"^\s*(income\s+before|pre-?tax|ebt|earnings before tax)", 0.90)]),
    ("income_tax_expense", [(r"^\s*(income\s+taxes|provision\s+for\s+income\s+tax)", 0.92),
                            (r"^\s*tax\s+expense\s*$", 0.85)]),
    ("net_income", [(r"^\s*(net\s+(income|earnings|profit)|profit\s+for\s+the\s+year)\s*(\(\w+\))?\s*$", 0.95),
                    (r"^\s*net\s+income\b", 0.85)]),
    ("da", [(r"^\s*(d\s*&\s*a|depreciation\s*(?:&|,|and)\s*amortization|amortization)\s*(\(\w+\))?\s*$", 0.93),
            (r"^\s*depreciation\b", 0.85)]),
    ("ebitda", [(r"^\s*ebitda\s*$", 0.95)]),
    ("operating_cash_flow", [(r"^\s*(net\s+)?cash\s*(provided\s*(by|from)|flow)\s*(from|in)\s*operating", 0.95),
                             (r"^\s*operating\s+cash\s+flow\s*$", 0.92),
                             (r"^\s*cfo\s*$", 0.85)]),
    ("da_cf", [(r"^\s*(depreciation|d\s*&\s*a).*(cash|addback|adjustment)", 0.85),
               (r"^\s*add.*depreciation", 0.80)]),
    ("capex", [(r"^\s*(capital\s+expenditure|purchase[s]?\s+of\s+(property|ppe|fixed\s+assets|capital))\b", 0.95),
               (r"^\s*capex\s*$", 0.92),
               (r"^\s*payments?\s+to\s+acquire\b", 0.85)]),
    ("change_nwc", [(r"^\s*(change|increase|decrease)\s+in\s+net\s+working\s+capital\s*$", 0.95),
                    (r"^\s*chg\.?\s*nwc\s*$", 0.90),
                    (r"^\s*change\s+in\s+working\s+capital\b", 0.85)]),
    ("cash", [(r"^\s*(cash\s+(&\s+cash\s+equivalents|and\s+cash\s+equivalents)|cash\s+\(?\w*\)?)\s*(\(\w+\))?\s*$", 0.93),
              (r"^\s*cash\s*&?\s*equivalents\b", 0.85)]),
    ("short_term_debt", [(r"^\s*(short[-\s]?term\s+debt|current\s+portion\s+of\s+(long[-\s]?term\s+)?debt|notes\s+payable)\s*$", 0.92),
                         (r"^\s*short[-\s]?term\s+borrowings\b", 0.88)]),
    ("long_term_debt", [(r"^\s*(long[-\s]?term\s+debt|non[-\s]?current\s+debt)(\s+\(?\w+\)?)?\s*$", 0.93),
                        (r"^\s*long[-\s]?term\s+loans\b", 0.85)]),
    ("total_debt", [(r"^\s*total\s+(interest[-\s]?bearing\s+)?debt\s*$", 0.97),
                    (r"^\s*total\s+borrowings\s*$", 0.93)]),
    ("current_assets", [(r"^\s*total\s+current\s+assets\s*$", 0.97)]),
    ("current_liabilities", [(r"^\s*total\s+current\s+liabilities\s*$", 0.97)]),
    ("accounts_receivable", [(r"^\s*(trade\s+)?accounts?\s+receivable\b", 0.93),
                             (r"^\s*receivables\b", 0.80)]),
    ("inventory", [(r"^\s*(total\s+)?inventor(y|ies)(\s+net)?\s*$", 0.92)]),
    ("accounts_payable", [(r"^\s*(trade\s+)?accounts?\s+payable\b", 0.93)]),
    ("total_assets", [(r"^\s*total\s+assets\s*$", 0.98)]),
    ("total_liabilities", [(r"^\s*total\s+liabilities\s*$", 0.98)]),
    ("shareholders_equity", [(r"^\s*total\s+(shareholders|stockholders)[‘'\s]*\s*equity\b", 0.97),
                             (r"^\s*(shareholders|stockholders)[‘'\s]*\s*equity\s*$", 0.90)]),
    ("shares_outstanding", [(r"^\s*(weighted\s+average\s+)?(number\s+of\s+)?(ordinary\s+)?shares\s+outstanding\b", 0.90),
                            (r"^\s*shares\s+outstanding\s*$", 0.95),
                            (r"^\s*issued\s+share", 0.80)]),
]

SHEET_HINTS = {
    "income": ["income statement", "profit and loss", "p&l", "statement of operations",
               "statement of comprehensive income", "operations"],
    "balance": ["balance sheet", "statement of financial position", "statement of financial condition"],
    "cashflow": ["cash flow", "cashflow", "statement of cash flows"],
    "assumptions": ["assumption", "forecast", "driver"],
    "debt": ["debt schedule", "debt detail", "borrowings"],
    "other": ["instruction", "readme", "template", "about"],
}

PERIOD_PATTERNS = [
    re.compile(r"^(fy|cy)\s*['\"]?(\d{2,4})$", re.I),
    re.compile(r"^(\d{4})$"),
    re.compile(r"^(dec|mar|jun|sep|jan|feb|apr|may|jul|aug|oct|nov)[-\s/](\d{2,4})$", re.I),
    re.compile(r"^h[12]\s*['\"]?(\d{2,4})$", re.I),
    re.compile(r"^(fy\s*)?(dec|q[1-4])?\s*['\"]?(\d{2,4})\s*(fy)?$", re.I),
]

UNIT_HINTS = [
    (re.compile(r"\(?\s*000[,.]000[,.]000\s*s?\)?|\bin\s+billions\b|\bbillions\s+of\s+(us)?d", re.I), 1e9),
    (re.compile(r"\(?\s*000[,.]000\s*s?\)?|\bin\s+millions\b|\bmillions\s+of\s+(us)?d", re.I), 1e6),
    (re.compile(r"\(?\s*000\s*s\)?|\bin\s+thousands\b|\bthousands\s+of\s+(us)?d", re.I), 1e3),
]

ASSUMPTION_PATTERNS: list[tuple[str, str, float]] = [
    # (regex on label, assumption key, unit scale if percent typed as number)
    (r"^revenue\s+growth", "revenue_growth", 1.0),
    (r"^ebit\s+margin", "ebit_margin", 1.0),
    (r"^tax\s+rate", "tax_rate", 1.0),
    (r"^terminal\s+growth", "terminal_growth", 1.0),
    (r"^exit\s+multiple", "exit_multiple", 1.0),
    (r"^d\s*&\s*a\s*/\s*revenue|d&a\s+as\s+%|da_pct", "da_pct", 1.0),
    (r"^capex\s*/\s*revenue|capex\s+as\s+%|capex_pct", "capex_pct", 1.0),
    (r"^nwc\s*/\s*revenue|nwc\s+as\s+%|nwc_pct", "nwc_pct", 1.0),
    (r"^risk[-\s]?free", "risk_free_rate", 1.0),
    (r"^market\s+risk\s+premium|equity\s+risk\s+premium", "market_risk_premium", 1.0),
    (r"^beta", "beta", 1.0),
    (r"^cost\s+of\s+debt|interest\s+rate\s+on\s+debt", "cost_of_debt", 1.0),
    (r"^target\s+(d/?e|debt\s*/\s*equity)", "target_de", 1.0),
    (r"^cost\s+of\s+equity|expected\s+return", "cost_of_equity", 1.0),
    (r"^share\s+price|current\s+price|stock\s+price", "share_price", 1.0),
    (r"^shares\s+outstanding", "shares_outstanding", 1.0),
    (r"^net\s+debt", "net_debt", 1.0),
    (r"^forecast\s+years|projection\s+years", "forecast_years", 1.0),
]


@dataclass
class _Detected:
    sheet: str
    kind: str
    unit_scale: float = 1.0
    unit_explicit: bool = False
    periods: dict[int, int] = field(default_factory=dict)  # column index -> fiscal year
    rows: dict[str, dict] = field(default_factory=dict)  # key -> {label, row, cells{year: value}}
    ambiguous: dict[str, list[str]] = field(default_factory=dict)


def _norm(label) -> str:
    if label is None:
        return ""
    s = str(label).replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", s).strip()


def _classify_sheet(name: str, labels: list[str]) -> str:
    lname = name.lower()
    for kind, hints in SHEET_HINTS.items():
        if any(h in lname for h in hints):
            return kind
    joined = " | ".join(labels[:60]).lower()
    scores = {
        "income": len(re.findall(r"revenue|net sales|gross profit|operating income|net income", joined)),
        "balance": len(re.findall(r"total assets|total liabilities|equity|receivable|payable", joined)),
        "cashflow": len(re.findall(r"operating activities|investing activities|financing activities|capex", joined)),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "other"


def _detect_unit_scale(ws, max_scan_rows: int = 8) -> tuple[float, bool]:
    """Returns (scale, explicit) — explicit=False when no unit hint was found."""
    for row in ws.iter_rows(min_row=1, max_row=max_scan_rows):
        for cell in row:
            if isinstance(cell.value, str):
                for rx, scale in UNIT_HINTS:
                    if rx.search(cell.value):
                        return scale, True
    return 1.0, False


def _match_metric(label: str) -> tuple[str, float] | None:
    text = _norm(label).lower().lstrip("*")
    text = text.replace("(usd)", "").replace("(us$", "").strip()
    for key, patterns in PATTERNS:
        for rx, conf in patterns:
            if re.match(rx, text, re.I):
                return key, conf
    return None


def _to_number(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("$", "").replace("%", "")
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        try:
            x = float(s)
        except ValueError:
            return None
        return -x if neg else x
    return None


class ExcelProvider(DataProvider):
    name = "excel"
    kind = "excel"

    MAX_SHEETS = 40
    MAX_ROWS = 500
    MAX_COLS = 60

    def __init__(self) -> None:
        self.assumption_values: dict[str, float] = {}
        self.debt_instruments: list[dict] = []
        self.mapping_notes: list[MappingNote] = []

    def validate_file(self, path: Path, original_name: str) -> None:
        ext = Path(original_name or path.name).suffix.lower()
        allowed = [e.strip() for e in settings.allowed_upload_extensions.split(",") if e.strip()]
        if ext not in allowed:
            raise ExcelValidationError(
                f"Unsupported file type '{ext}'. Allowed: {', '.join(allowed)}",
                hint="Save your workbook as .xlsx and retry.",
            )
        size = path.stat().st_size
        if size > settings.max_upload_bytes:
            raise ExcelValidationError(
                f"File too large ({size:,} bytes). Limit is {settings.max_upload_bytes:,} bytes.",
            )
        if size == 0:
            raise ExcelValidationError("The uploaded file is empty.")

    async def fetch(self, path: str | Path, original_name: str | None = None,
                    company_name: str | None = None, **_) -> ProviderPayload:
        path = Path(path)
        self.validate_file(path, original_name or path.name)
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 — openpyxl raises many types
            raise ExcelValidationError(
                f"Could not open workbook: {exc}",
                hint="Ensure the file is a valid .xlsx produced by Excel/LibreOffice/Google Sheets.",
            ) from exc

        try:
            if wb.sheetnames and len(wb.sheetnames) > self.MAX_SHEETS:
                raise ExcelValidationError(f"Workbook has too many sheets ({len(wb.sheetnames)}).")

            detected: list[_Detected] = []
            previews: list[dict] = []
            assumption_values: dict[str, float] = {}
            debt_instruments: list[dict] = []
            company_hints: dict[str, str] = {}

            for ws in wb.worksheets:
                labels, preview_rows = self._scan_rows(ws)
                if preview_rows:
                    previews.append({"sheet": ws.title, "rows": preview_rows[:12]})
                kind = _classify_sheet(ws.title, labels)
                if kind == "assumptions":
                    assumption_values.update(self._parse_assumptions(ws))
                if kind == "debt":
                    debt_instruments.extend(self._parse_debt(ws))
                if kind in ("income", "balance", "cashflow"):
                    det = self._extract_statement(ws, kind)
                    if det.rows:
                        detected.append(det)

            periods = self._merge(detected)
            if not periods:
                raise ExcelValidationError(
                    "No financial statement rows could be identified in this workbook.",
                    hint="Download the template and match its sheet/row structure, "
                         "or rename your sheets to 'Income Statement', 'Balance Sheet', 'Cash Flow'.",
                )

            missing = self._missing(periods)
            company = CompanyInfo(
                name=company_name or _norm(company_hints.get("name")) or path.stem.replace("_", " ").title(),
                currency="USD", is_public=False,
                source_type=SourceType.UPLOADED_EXCEL, source="Uploaded Excel",
                source_url=None, retrieved_at=today(), provider=self.name,
                notes=["Private-company inputs are labelled as user data; "
                       "market-based inputs (beta, price) must be supplied by the user or comparables."],
            )
            mapping_notes, ambiguous_warnings = self._mapping_notes(detected)
            sources = self._sources(detected, assumption_values, debt_instruments)

            payload = ProviderPayload(
                company=company, periods=periods, sources=sources, missing=missing,
                warnings=ambiguous_warnings, preview=previews,
            )
            self.assumption_values = assumption_values
            self.debt_instruments = debt_instruments
            self.mapping_notes = mapping_notes
            return payload
        finally:
            wb.close()

    # -- internals ----------------------------------------------------------
    def _scan_rows(self, ws) -> tuple[list[str], list[list]]:
        labels: list[str] = []
        preview: list[list] = []
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=min(self.MAX_ROWS, 200),
                                             max_col=min(self.MAX_COLS, 20), values_only=True), start=1):
            preview.append([("" if v is None else v) for v in row])
            first = next((v for v in row if isinstance(v, str) and v.strip()), None)
            if first:
                labels.append(_norm(first))
        return labels, preview

    def _extract_statement(self, ws, kind: str) -> _Detected:
        det = _Detected(sheet=ws.title, kind=kind)
        det.unit_scale, det.unit_explicit = _detect_unit_scale(ws)
        rows_cache: list[tuple[int, list]] = []
        header_map: dict[int, int] = {}

        for r_idx, row in enumerate(ws.iter_rows(
                min_row=1, max_row=self.MAX_ROWS, max_col=self.MAX_COLS, values_only=True), start=1):
            rows_cache.append((r_idx, list(row)))
            if not header_map:
                hits = {}
                for c_idx, v in enumerate(row, start=1):
                    if isinstance(v, str):
                        for rx in PERIOD_PATTERNS:
                            m = rx.match(_norm(v))
                            if m:
                                digits = [g for g in m.groups() if g and g.isdigit()]
                                if digits:
                                    year = int(digits[-1])
                                    if year < 100:
                                        year += 2000 if year < 70 else 1900
                                    if 1990 <= year <= 2100:
                                        hits[c_idx] = year
                                        break
                if len(hits) >= 2:
                    header_map = hits
                    det.periods = dict(hits)

        if not det.periods:
            return det

        seen: dict[str, tuple[str, float, int, list]] = {}
        ambiguous: dict[str, list[str]] = {}
        for r_idx, row in rows_cache:
            label_cell = next((v for v in row if isinstance(v, str) and v.strip()), None)
            if not label_cell:
                continue
            m = _match_metric(label_cell)
            if not m:
                continue
            key, conf = m
            cells: dict[int, float] = {}
            for col, year in det.periods.items():
                if col - 1 < len(row):
                    n = _to_number(row[col - 1])
                    if n is not None:
                        cells[year] = n  # raw as-typed; scaling applied in _merge
            if not cells:
                continue
            if key in seen:
                prev_conf = seen[key][1]
                ambiguous.setdefault(key, []).append(f"{ws.title}!row{r_idx} '{_norm(label_cell)}'")
                if conf > prev_conf:
                    seen[key] = (_norm(label_cell), conf, r_idx, cells)
            else:
                seen[key] = (_norm(label_cell), conf, r_idx, cells)

        for key, (label, conf, r_idx, cells) in seen.items():
            det.rows[key] = {"label": label, "confidence": conf, "row": r_idx, "cells": cells}
        det.ambiguous = ambiguous
        return det

    def _merge(self, detected: list[_Detected]) -> list[PeriodData]:
        order = {"income": 0, "cashflow": 1, "balance": 2}
        detected = sorted(detected, key=lambda d: order.get(d.kind, 9))
        # Unit inheritance: when only one statement sheet declares units
        # ('in thousands'), the whole workbook is assumed to share them.
        explicit = {d.unit_scale for d in detected if d.unit_explicit and d.unit_scale != 1.0}
        if len(explicit) == 1:
            shared = explicit.pop()
            for d in detected:
                if not d.unit_explicit:
                    d.unit_scale = shared
                    d.inherited_units = True
        by_year: dict[int, dict[str, SourcedValue]] = {}
        sheets: set[str] = set()
        for det in detected:
            sheets.add(det.sheet)
            for key, info in det.rows.items():
                for year, raw in info["cells"].items():
                    if key in by_year.get(year, {}):
                        continue  # first (highest-priority sheet) wins
                    value = raw * det.unit_scale
                    by_year.setdefault(year, {})[key] = SourcedValue(
                        value=value, unit=Unit.COUNT if key == "shares_outstanding" else Unit.CURRENCY,
                        period=f"FY{year}",
                        source_type=SourceType.UPLOADED_EXCEL,
                        source=f"Uploaded Excel — {det.sheet}",
                        retrieved_at=today(),
                        status=ValueStatus.USER_DATA,
                        note=f"label '{info['label']}' (confidence {info['confidence']:.0%})",
                        original_value=raw,
                        original_unit=(f"sheet units x{det.unit_scale:g}"
                                       + (" (inherited from workbook header)"
                                          if getattr(det, "inherited_units", False) else "")),
                        cell_ref=f"{det.sheet}!row{info['row']}",
                    )

        periods: list[PeriodData] = []
        for year in sorted(by_year):
            metrics = by_year[year]
            _derive_derived(metrics, year)
            periods.append(PeriodData(
                period=f"FY{year}", fiscal_year=year, end_date=date(year, 12, 31),
                currency="USD", unit_scale=1.0, metrics=metrics,
            ))
        return periods

    def _mapping_notes(self, detected: list[_Detected]) -> tuple[list[MappingNote], list[str]]:
        notes: list[MappingNote] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for det in detected:
            for key, info in det.rows.items():
                if key in seen:
                    continue
                seen.add(key)
                amb = det.ambiguous.get(key, [])
                notes.append(MappingNote(
                    field=key, field_label=key.replace("_", " ").title(),
                    mapped_from=f"{det.sheet}!row{info['row']} ('{info['label']}')",
                    confidence=info["confidence"], ambiguous=bool(amb),
                    candidates=amb,
                ))
                if amb:
                    warnings.append(
                        f"'{info['label']}' mapped to {key} but similar labels also exist: {', '.join(amb)}. "
                        "Confirm the mapping on the Data Review page."
                    )
        return notes, warnings

    @staticmethod
    def _missing(periods: list[PeriodData]) -> list[str]:
        if not periods:
            return ["revenue", "ebit", "net_income"]
        latest = periods[-1]
        critical = ["revenue", "ebit"]
        return [k for k in critical if latest.value(k) is None]

    def _parse_assumptions(self, ws) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in ws.iter_rows(min_row=1, max_row=100, max_col=6, values_only=True):
            label = next((v for v in row if isinstance(v, str)), None)
            if not label:
                continue
            nums = [ _to_number(v) for v in row if _to_number(v) is not None ]
            if not nums:
                continue
            text = _norm(label).lower()
            for rx, key, _scale in ASSUMPTION_PATTERNS:
                if re.search(rx, text, re.I):
                    out[key] = nums[0]
                    break
        return out

    def _parse_debt(self, ws) -> list[dict]:
        out: list[dict] = []
        for row in ws.iter_rows(min_row=1, max_row=100, max_col=8, values_only=True):
            nums = [v for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(nums) >= 2:
                name = next((str(v) for v in row if isinstance(v, str) and v.strip()), "Debt instrument")
                amount, rate = float(nums[0]), float(nums[1])
                if rate > 1:  # typed as 5.5 meaning 5.5%
                    rate = rate / 100.0
                if amount > 0 and 0 <= rate <= 0.5:
                    out.append({"name": name, "amount": amount, "rate": rate})
        return out

    @staticmethod
    def _sources(detected: list[_Detected], assumptions: dict, debts: list[dict]) -> list:
        from ...schemas.common import SourceRecord
        return [SourceRecord(
            id="uploaded-excel",
            name="Uploaded Excel workbook",
            source_type=SourceType.UPLOADED_EXCEL,
            retrieved_at=today(),
            description="User-provided financial statements; values as entered in the workbook.",
            metrics=sorted({k for d in detected for k in d.rows}),
        )]


def _derive_derived(metrics: dict[str, SourcedValue], year: int) -> None:
    period = f"FY{year}"

    def calc(key: str, value: float, formula: str) -> None:
        metrics[key] = SourcedValue(
            value=value, unit=Unit.CURRENCY, period=period,
            source_type=SourceType.MODEL_CALCULATION,
            source="Derived from uploaded values", retrieved_at=today(),
            status=ValueStatus.CALCULATED, note=formula,
        )

    g = lambda k: metrics[k].value if k in metrics and metrics[k].value is not None else None
    rev, cogs, gp, ebit, da = g("revenue"), g("cogs"), g("gross_profit"), g("ebit"), g("da")
    if gp is None and rev is not None and cogs is not None:
        calc("gross_profit", rev - cogs, "Gross Profit = Revenue - COGS")
    if ebit is None and gp is not None and metrics.get("operating_expenses") is not None \
            and metrics["operating_expenses"].value is not None:
        calc("ebit", gp - metrics["operating_expenses"].value, "EBIT = Gross Profit - Operating Expenses")
        ebit = g("ebit")
    ni, tax = g("net_income"), g("income_tax_expense")
    ebt = g("ebt")
    if ebt is None and ni is not None and tax is not None:
        calc("ebt", ni + tax, "EBT = Net Income + Income Tax Expense")
        ebt = g("ebt")
    # Workbook has no EBIT row — reconstruct from pre-tax income so the
    # ebit_margin driver stays derivable (mirrors the SEC provider; same
    # bank-vs-industrial heuristic, every path labelled with its formula).
    if ebit is None and ebt is not None:
        interest, revenue = g("interest_expense"), g("revenue")
        if (interest is not None and revenue not in (None, 0)
                and abs(interest) / abs(revenue) > 0.20):
            calc("ebit", ebt,
                 "EBIT ≈ EBT (interest exceeds 20% of revenue — revenue likely "
                 "net of interest, so no add-back; no EBIT row in workbook)")
        elif interest is not None:
            calc("ebit", ebt + abs(interest),
                 "EBIT = EBT + Interest Expense (no EBIT row in workbook)")
        else:
            calc("ebit", ebt,
                 "EBIT ≈ EBT (no EBIT or interest rows in workbook — pre-tax "
                 "income used as the closest available measure)")
        ebit = g("ebit")
    if "ebitda" not in metrics and ebit is not None and da is not None:
        calc("ebitda", ebit + da, "EBITDA = EBIT + D&A")
    if "total_debt" not in metrics:
        st, lt = g("short_term_debt"), g("long_term_debt")
        if st is not None or lt is not None:
            calc("total_debt", (st or 0.0) + (lt or 0.0), "Total Debt = Short-Term Debt + Long-Term Debt")
