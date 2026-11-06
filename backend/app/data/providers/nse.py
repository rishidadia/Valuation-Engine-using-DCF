"""NSE India provider — fundamentals and market data straight from NSE India.

Every number comes from an NSE surface (no yfinance, no third-party scraper):

  * ``/api/corporates-financial-results``  annual results filed with NSE
  * ``/api/integrated-filing-results``     SEBI integrated filings (2025 onwards)
  * nsearchives.nseindia.com XBRL documents — the actual statements as filed
  * ``sec_bhavdata_full_DDMMYYYY.csv``     official daily bhavcopy closes
  * ``/api/historicalOR/indicesHistory``   NIFTY 50 benchmark closes

The quote API (``/api/quote-equity``) sits behind an Akamai bot check and is
deliberately not used: prices come from NSE's published bhavcopy files instead.
Values are in absolute INR and keep the XBRL tag they came from, so every
figure stays traceable to a filed document (never invented).
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx

from ...core.config import settings
from ...core.errors import ProviderError, TickerNotFoundError
from ...schemas.common import SourceRecord, SourceType, SourcedValue, Unit, ValueStatus
from ...schemas.company import CompanyInfo, PeriodData
from .base import HttpClient, today

logger = logging.getLogger(__name__)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
NSE_API_HEADERS = {**NSE_HEADERS, "Referer": "https://www.nseindia.com/"}

LIQUID_SERIES = {"EQ", "BE", "BZ", "SM"}

# --- tag maps (Ind-AS / in-bse-fin taxonomy used by NSE filings) ------------

FLOW_MAP: dict[str, list[str]] = {
    "revenue": ["RevenueFromOperations"],
    "interest_expense": ["FinanceCosts", "InterestExpense", "InterestExpended"],
    "ebt": ["ProfitBeforeTax", "ProfitBeforeExtraordinaryItemsAndTax",
            "ProfitLossFromOrdinaryActivitiesBeforeTax"],
    "income_tax_expense": ["TaxExpense", "IncomeTaxExpense"],
    # Banks/NBFCs use their own profit tags (note "ProfitLossForThePeriod").
    "net_income": ["ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations",
                   "ProfitLossForThePeriod", "ProfitLossFromOrdinaryActivitiesAfterTax",
                   "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"],
    "da": ["DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"],
    "operating_cash_flow": ["CashFlowsFromUsedInOperatingActivities"],
    "da_cf": ["AdjustmentsForDepreciationAndAmortisationExpense"],
}

# Fallback used only when a filer tags no revenue-from-operations concept at all
# (banks and some NBFCs report total income instead).
REVENUE_FALLBACK = ["Income"]

INSTANT_MAP: dict[str, list[str]] = {
    "cash": ["CashAndCashEquivalents", "CashAndCashEquivalentsCashFlowStatement",
             "CashAndBalancesWithReserveBankOfIndia"],
    "short_term_debt": ["BorrowingsCurrent"],
    "long_term_debt": ["BorrowingsNoncurrent"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "accounts_receivable": ["TradeReceivablesCurrent"],
    "inventory": ["Inventories"],
    "accounts_payable": ["TradePayablesCurrent"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["Equity", "EquityAttributableToOwnersOfParent"],
}

CAPEX_TAGS = [
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PurchaseOfTangibleAssetsClassifiedAsInvestingActivities",
    "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    "PurchaseOfInvestmentPropertyClassifiedAsInvestingActivities",
]

REVENUE_TAG = "RevenueFromOperations"
PAID_UP_TAG = "PaidUpValueOfEquityShareCapital"
FACE_VALUE_TAG = "FaceValueOfEquityShareCapital"

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"


# ---------------------------------------------------------------------------
# Filing metadata
# ---------------------------------------------------------------------------

@dataclass
class AnnualFiling:
    symbol: str
    fiscal_year: int
    period_end: date
    consolidated: bool
    audited: bool
    xbrl_url: str
    company_name: str | None = None
    isin: str | None = None
    broadcast: str | None = None
    source: str = "legacy"


@dataclass
class FilingStatements:
    """Full-year duration facts + period-end instant facts of one document."""

    period_start: date | None = None
    period_end: date | None = None
    flow: dict[str, float] = field(default_factory=dict)
    instant: dict[str, float] = field(default_factory=dict)
    dimensional_contexts: int = 0
    legacy_cumulative: bool = False


def parse_nse_date(value: str | None) -> date | None:
    """NSE dates appear as ``31-Mar-2024``, ``31-MAR-2026`` or ``12-Apr-2024 21:04``."""
    if not value:
        return None
    txt = value.strip().split(" ")[0]
    for fmt, prepare in (("%d-%b-%Y", str.title), ("%d-%m-%Y", str), ("%Y-%m-%d", str)):
        try:
            return datetime.strptime(prepare(txt), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# XBRL parsing
# ---------------------------------------------------------------------------

def parse_xbrl(xml_text: str) -> FilingStatements:
    """Extract the annual duration and period-end instant facts from a filing.

    Quarterly columns are present in the same document, so facts are selected
    by context: the longest non-dimensional duration in the document (the full
    year) and the period-end instant. Segment/dimensional contexts are ignored
    so a segment total can never masquerade as the company total.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProviderError(f"NSE returned an unparseable XBRL document: {exc}") from exc

    contexts: dict[str, tuple[date | None, date | None, bool]] = {}
    for el in root:
        if not el.tag.endswith("}context"):
            continue
        period = el.find(f".//{XBRLI}period")
        if period is None:
            continue
        start = parse_nse_date(period.findtext(f"{XBRLI}startDate"))
        end = parse_nse_date(period.findtext(f"{XBRLI}endDate"))
        instant = parse_nse_date(period.findtext(f"{XBRLI}instant"))
        dimensional = (
            el.find(f".//{XBRLDI}explicitMember") is not None
            or el.find(f".//{XBRLDI}typedMember") is not None
        )
        contexts[el.get("id") or ""] = (start, end or instant, dimensional)

    flows = {(s, e): cid for cid, (s, e, dim) in contexts.items()
             if s and e and not dim and 300 <= (e - s).days <= 400}
    instants = {e: cid for cid, (s, e, dim) in contexts.items()
                if s is None and e and not dim}
    # Balance-sheet facts exist for both the current and the comparative date;
    # only the latest instant belongs to this filing's own period.
    instant_ctx = instants[max(instants)] if instants else None

    statements = FilingStatements(dimensional_contexts=sum(1 for c in contexts.values() if c[2]))
    if flows:
        (start, end), flow_ctx = max(flows.items(), key=lambda kv: (kv[0][1] - kv[0][0]).days)
        statements.period_start, statements.period_end = start, end
    else:
        # Legacy NSE filings put the cumulative (full-year) column in a Q4
        # context named ``FourD``; in some documents that context is only
        # referenced, never declared, so fall back to the id itself.
        flow_ctx = next((cid for cid, (s, e, dim) in contexts.items()
                         if not dim and s and e and _is_cumulative_id(cid)), None)
        if flow_ctx is None:
            refs = {el.get("contextRef") for el in root}
            flow_ctx = next((cid for cid in refs if cid and _is_cumulative_id(cid)), None)
        if flow_ctx:
            statements.legacy_cumulative = True
            if flow_ctx in contexts and contexts[flow_ctx][1]:
                statements.period_end = contexts[flow_ctx][1]
        elif instants:
            statements.period_end = max(instants)
        if instant_ctx is None:
            refs = {el.get("contextRef") for el in root}
            instant_ctx = next((cid for cid in ("OneI", "FourI") if cid in refs), None)

    period_dates: dict[str, date] = {}
    for el in root:
        tag = el.tag
        if "}" not in tag:
            continue
        name = tag.rsplit("}", 1)[1]
        if name in ("context", "unit", "schemaRef"):
            continue
        cid = el.get("contextRef")
        raw = (el.text or "").strip()
        if not raw:
            continue
        if name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod",
                    "DateOfStartOfFinancialYear", "DateOfEndOfFinancialYear"):
            if flow_ctx and cid == flow_ctx and name not in period_dates:
                parsed = parse_nse_date(raw)
                if parsed:
                    period_dates[name] = parsed
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if el.get("sign") == "-":  # iXBRL-style sign attribute
            value = -value
        if flow_ctx and cid == flow_ctx:
            statements.flow[name] = value
        elif instant_ctx and cid == instant_ctx:
            statements.instant[name] = value

    # Filed period dates are authoritative when present (legacy Q4 contexts lie).
    start = period_dates.get("DateOfStartOfReportingPeriod") or period_dates.get("DateOfStartOfFinancialYear")
    end = period_dates.get("DateOfEndOfReportingPeriod") or period_dates.get("DateOfEndOfFinancialYear")
    if start and end:
        statements.period_start, statements.period_end = start, end
        statements.legacy_cumulative = False
    return statements


def _is_cumulative_id(context_id: str) -> bool:
    """``FourD`` is NSE's legacy cumulative (fourth-column) duration context."""
    return context_id.strip().lower() == "fourd"


def _first(statements: FilingStatements, tags: list[str], *, instant: bool) -> tuple[str, float] | None:
    bucket = statements.instant if instant else statements.flow
    for tag in tags:
        if tag in bucket:
            return tag, bucket[tag]
    return None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class NseIndiaProvider:
    """NSE-listed company fundamentals + market data, in INR."""

    name = "nse_india"

    def __init__(self) -> None:
        self._filings_cache: dict[str, list[AnnualFiling]] = {}
        self.http = HttpClient(headers=NSE_API_HEADERS)

    # -- NSE JSON -----------------------------------------------------------
    async def _api(self, path: str, params: dict) -> list | dict:
        url = f"{settings.nse_base_url}{path}"
        try:
            return await self.http.json(url, params=params, headers=NSE_API_HEADERS)
        except ProviderError as exc:
            raise ProviderError(
                f"NSE India rejected the request to {path}: {exc.detail}",
                hint="NSE rate-limits automated clients. Retry in a minute, or set "
                     "KITE_API_KEY/KITE_ACCESS_TOKEN to route prices through Zerodha Kite.",
            ) from exc

    async def annual_filings(self, symbol: str) -> list[AnnualFiling]:
        """Annual results filings for ``symbol`` from both NSE filing feeds.

        NSE moved financial results to its "Integrated Filing" feed for periods
        ending March 2025 onwards, so both feeds are merged and de-duplicated by
        (fiscal year, consolidated/standalone) keeping the most recent filing.
        """
        symbol = symbol.strip().upper()
        if symbol in self._filings_cache:
            return self._filings_cache[symbol]

        legacy = await self._api(settings.nse_financial_results_path,
                                 {"index": "equities", "period": "Annual", "symbol": symbol})
        merged: dict[tuple[int, bool], AnnualFiling] = {}
        for row in legacy if isinstance(legacy, list) else []:
            end = parse_nse_date(row.get("toDate"))
            if not end or end.month != 3 or not _valid_xbrl_url(row.get("xbrl")):
                continue
            filing = AnnualFiling(
                symbol=symbol, fiscal_year=end.year, period_end=end,
                consolidated=str(row.get("consolidated", "")).lower().startswith("consolidated"),
                audited=str(row.get("audited", "")).lower().startswith("audited"),
                xbrl_url=row["xbrl"], company_name=row.get("companyName"),
                isin=row.get("isin"), broadcast=row.get("broadCastDate"), source="legacy",
            )
            merged[(filing.fiscal_year, filing.consolidated)] = filing

        try:
            integrated = await self._api(settings.nse_integrated_filings_path,
                                         {"symbol": symbol, "period": "Annual"})
        except ProviderError:
            integrated = {}  # older feed alone is still usable
        rows = integrated.get("data", []) if isinstance(integrated, dict) else []
        for row in rows:
            if (row.get("type") != "Integrated Filing- Financials"
                    or not _valid_xbrl_url(row.get("xbrl"))):
                continue
            end = parse_nse_date(row.get("qe_Date"))
            if not end or end.month != 3:
                continue
            filing = AnnualFiling(
                symbol=symbol, fiscal_year=end.year, period_end=end,
                consolidated=str(row.get("consolidated", "")).lower().startswith("consolidated"),
                audited=str(row.get("audited", "")).lower().startswith("audited"),
                xbrl_url=row["xbrl"], company_name=row.get("cmName"),
                broadcast=row.get("broadcast_Date"), source="integrated",
            )
            key = (filing.fiscal_year, filing.consolidated)
            previous = merged.get(key)
            if previous is None or str(filing.broadcast or "") >= str(previous.broadcast or ""):
                merged[key] = filing

        filings = sorted(merged.values(), key=lambda f: (f.fiscal_year, f.consolidated))
        if not filings:
            raise TickerNotFoundError(
                f"NSE India has no annual results for symbol '{symbol}'.",
                hint="Use the NSE trading symbol (e.g. RELIANCE, TCS, HDFCBANK). "
                     "BSE-only listings are not supported.",
            )
        self._filings_cache[symbol] = filings
        return filings

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=max(settings.http_timeout_seconds, 30.0),
                                 follow_redirects=True, headers=NSE_API_HEADERS)

    async def _download_many(self, urls: list[str], concurrency: int = 4) -> list[str | None]:
        sem = asyncio.Semaphore(concurrency)

        async with self._client() as client:
            async def one(url: str) -> str | None:
                async with sem:
                    try:
                        resp = await client.get(url)
                        if resp.status_code != 200:
                            return None
                        return resp.text
                    except httpx.HTTPError:
                        return None

            return list(await asyncio.gather(*(one(u) for u in urls)))

    # -- fundamentals -------------------------------------------------------
    async def fetch(self, symbol: str, years: int | None = None, **_) -> dict:
        """Build annual periods (INR) from NSE XBRL filings."""
        symbol = symbol.strip().upper()
        filings = await self.annual_filings(symbol)

        years = min(years or settings.nse_max_filing_downloads, settings.nse_max_filing_downloads)
        by_year = _select_filings(filings, years)
        warnings: list[str] = []
        if any(not f.consolidated for f in by_year):
            warnings.append(
                "Some periods use standalone (non-consolidated) filings — consolidated "
                "statements were preferred wherever NSE published them."
            )
        skipped = [f for f in filings if not f.audited]
        if skipped:
            warnings.append(
                f"Ignored {len(skipped)} un-audited NSE filing(s); only audited annual "
                "results are used."
            )

        documents = await self._download_many([f.xbrl_url for f in by_year])
        periods: list[PeriodData] = []
        provenance_metrics: set[str] = set()
        for filing, xml in zip(by_year, documents):
            if not xml:
                warnings.append(f"FY{filing.fiscal_year}: NSE XBRL document could not be downloaded.")
                continue
            try:
                statements = parse_xbrl(xml)
            except ProviderError as exc:
                warnings.append(f"FY{filing.fiscal_year}: {exc.detail}")
                continue
            period = _build_period(filing, statements, warnings)
            if period is None:
                continue
            periods.append(period)
            provenance_metrics.update(period.metrics)

        if not periods:
            raise ProviderError(
                f"NSE filings for '{symbol}' were found but no statements could be read.",
                hint="The XBRL documents may be temporarily unavailable; retry later.",
            )

        latest = by_year[-1]
        company = CompanyInfo(
            name=latest.company_name or symbol,
            ticker=symbol,
            exchange="NSE",
            isin=latest.isin,
            currency="INR",
            is_public=True,
            source_type=SourceType.PUBLIC_API,
            source="NSE India annual filings (XBRL)",
            source_url=f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}",
            retrieved_at=today(),
            provider=self.name,
        )
        source = SourceRecord(
            id="nse-india-xbrl",
            name="NSE India annual financial results (XBRL)",
            source_type=SourceType.PUBLIC_API,
            url=("https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
                 f"?symbol={symbol}"),
            retrieved_at=today(),
            description=("Audited annual statements as filed with the National Stock Exchange "
                         "of India (Ind-AS XBRL, consolidated where available). Amounts in INR."),
            metrics=sorted(provenance_metrics),
        )
        return {
            "company": company, "periods": periods, "sources": [source],
            "warnings": warnings, "missing": _missing_critical(periods),
            "filings": len(periods),
        }

    # -- market data: official bhavcopy -------------------------------------
    async def _bhavcopy_close(self, day: date, symbol: str) -> float | None:
        url = settings.nse_bhavcopy_url.format(date=day.strftime("%d%m%Y"))
        try:
            text = await self.http.text(url, headers=NSE_HEADERS)
        except ProviderError:
            return None
        return _parse_bhavcopy(text, symbol)

    async def latest_quote(self, symbol: str, lookback_days: int = 12) -> dict:
        """Latest official close from NSE's daily bhavcopy (skips weekends/holidays)."""
        symbol = symbol.strip().upper()
        end = today()
        for offset in range(lookback_days):
            day = end - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            close = await self._bhavcopy_close(day, symbol)
            if close is not None:
                return {"price": close, "currency": "INR", "date": day,
                        "exchange": "NSE", "instrument": "EQ"}
        raise ProviderError(
            f"NSE bhavcopy carried no trade for '{symbol}' in the last {lookback_days} days.",
            hint="Check the NSE symbol, or enter the share price manually on the Data Review page.",
        )

    async def _bhavcopy_closes(self, symbol: str, days: list[date]) -> dict[date, float]:
        sem = asyncio.Semaphore(4)

        async with self._client() as client:
            async def one(day: date) -> tuple[date, float | None]:
                url = settings.nse_bhavcopy_url.format(date=day.strftime("%d%m%Y"))
                async with sem:
                    try:
                        resp = await client.get(url)
                        if resp.status_code != 200:
                            return day, None
                        return day, _parse_bhavcopy(resp.text, symbol)
                    except httpx.HTTPError:
                        return day, None

            rows = await asyncio.gather(*(one(d) for d in days))
        return {d: v for d, v in rows if v is not None}

    # -- market data: NIFTY benchmark + beta --------------------------------
    async def index_closes(self, start: date, end: date,
                           index: str | None = None) -> dict[date, float]:
        """Daily NIFTY 50 closes from NSE's index history endpoint (chunked to 1y)."""
        index = index or settings.nse_benchmark_index
        out: dict[date, float] = {}
        cursor = start
        while cursor <= end:
            # NSE silently truncates long index-history ranges, so request one
            # month at a time — that also guarantees the true month-end close.
            chunk_end = min(cursor + timedelta(days=30), end)
            payload = await self._api(settings.nse_index_history_path, {
                "indexType": index,
                "from": cursor.strftime("%d-%m-%Y"),
                "to": chunk_end.strftime("%d-%m-%Y"),
            })
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            for row in rows:
                day = parse_nse_date(row.get("EOD_TIMESTAMP"))
                close = row.get("EOD_CLOSE_INDEX_VAL")
                if day and close is not None:
                    out[day] = float(close)
            cursor = chunk_end + timedelta(days=1)
        return out

    async def compute_beta(self, symbol: str, months: int | None = None) -> dict:
        """OLS beta vs NIFTY 50 on month-end closes from the official bhavcopy.

        Month-end sampling keeps this to ~24 small NSE downloads instead of ~500
        daily files; the window and observation count are reported so the
        estimate's precision is visible in the audit trail.
        """
        from ...valuation.beta import regression_beta

        symbol = symbol.strip().upper()
        months = max(int(months or settings.nse_beta_months), 13)
        end = today()
        start = end - timedelta(days=int(months * 31.5))
        index = await self.index_closes(start, end)
        if len(index) < 13:
            raise ProviderError(
                f"NSE returned only {len(index)} NIFTY 50 closes for the beta window.",
                hint="Retry later or provide beta manually on the Assumptions page.",
            )

        month_ends: dict[tuple[int, int], date] = {}
        for day in index:
            key = (day.year, day.month)
            if key not in month_ends or day > month_ends[key]:
                month_ends[key] = day
        dates = sorted(month_ends.values())[-(months + 1):]
        stock = await self._bhavcopy_closes(symbol, dates)
        common = sorted(set(stock) & set(index))
        if len(common) < 13:
            raise ProviderError(
                f"Only {max(len(common) - 1, 0)} month-end observations overlap between "
                f"'{symbol}' and {settings.nse_benchmark_index}.",
                hint="Provide beta manually on the Assumptions page.",
            )
        closes_s = [stock[d] for d in common]
        closes_b = [index[d] for d in common]
        s = [(closes_s[i] / closes_s[i - 1]) - 1 for i in range(1, len(closes_s))]
        b = [(closes_b[i] / closes_b[i - 1]) - 1 for i in range(1, len(closes_b))]
        beta, alpha, r2 = regression_beta(s, b)
        return {
            "beta": round(float(beta), 4),
            "alpha_daily": float(alpha),
            "r_squared": round(float(r2), 4),
            "observations": len(common) - 1,
            "benchmark": settings.nse_benchmark_index,
            "window": (f"{months}-month month-end closes, date-aligned "
                       f"({common[0]} to {common[-1]})"),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _valid_xbrl_url(url: str | None) -> bool:
    """Older NSE rows sometimes carry a placeholder ('.../xbrl/-') for no document."""
    return bool(url) and url.rstrip().lower().endswith(".xml")


def _select_filings(filings: list[AnnualFiling], years: int) -> list[AnnualFiling]:
    """Audited preferred, consolidated preferred, one filing per fiscal year."""
    audited = [f for f in filings if f.audited] or list(filings)
    by_year: dict[int, AnnualFiling] = {}
    # Sorting by (year, consolidated) makes the consolidated filing win per year;
    # the broadcast date makes a revised filing supersede the original.
    for filing in sorted(audited, key=lambda f: (f.fiscal_year, f.consolidated,
                                                 str(f.broadcast or ""))):
        by_year[filing.fiscal_year] = filing
    return [by_year[y] for y in sorted(by_year)][-years:]


def _build_period(filing: AnnualFiling, statements: FilingStatements,
                  warnings: list[str]) -> PeriodData | None:
    if not statements.flow and not statements.instant:
        warnings.append(f"FY{filing.fiscal_year}: XBRL document contained no numeric facts.")
        return None

    period_label = f"FY{filing.fiscal_year}"
    scope = "consolidated" if filing.consolidated else "standalone"
    window = (f"{statements.period_start} to {statements.period_end}"
              if statements.period_start and statements.period_end
              else f"period ended {statements.period_end}")
    base_note = (f"{scope} annual filing with NSE; {window}; "
                 f"filed {filing.broadcast or 'n/a'}")

    def retrieved(key: str, tag: str, value: float) -> SourcedValue:
        return SourcedValue(
            value=value, unit=Unit.COUNT if key == "shares_outstanding" else Unit.CURRENCY,
            currency="INR", period=period_label, source_type=SourceType.PUBLIC_API,
            source=f"NSE India XBRL {tag}", source_url=filing.xbrl_url,
            retrieved_at=today(), status=ValueStatus.RETRIEVED, note=base_note,
            original_value=value,
        )

    def calculated(key: str, value: float, formula: str) -> SourcedValue:
        return SourcedValue(
            value=value, unit=Unit.COUNT if key == "shares_outstanding" else Unit.CURRENCY,
            currency="INR", period=period_label,
            source_type=SourceType.MODEL_CALCULATION,
            source=f"Derived from NSE XBRL values ({key})",
            source_url=filing.xbrl_url, retrieved_at=today(),
            status=ValueStatus.CALCULATED, note=f"{formula} | {base_note}",
        )

    metrics: dict[str, SourcedValue] = {}
    for key, tags in FLOW_MAP.items():
        hit = _first(statements, tags, instant=False)
        if hit:
            metrics[key] = retrieved(key, *hit)

    if "revenue" not in metrics:
        hit = _first(statements, REVENUE_FALLBACK, instant=False)
        if hit:
            metrics["revenue"] = retrieved("revenue", *hit)
            warnings.append(
                f"{period_label}: no revenue-from-operations tag — total income reported "
                "by this filer is used as revenue. Verify on the Data Review page."
            )

    for key, tags in INSTANT_MAP.items():
        hit = _first(statements, tags, instant=True)
        if hit:
            metrics[key] = retrieved(key, *hit)

    # total debt = current + non-current borrowings (banks tag a single Borrowings line)
    st = metrics.get("short_term_debt")
    lt = metrics.get("long_term_debt")
    if st or lt:
        metrics["total_debt"] = calculated(
            "total_debt", (st.value if st else 0.0) + (lt.value if lt else 0.0),
            "Total Debt = Current Borrowings + Non-Current Borrowings",
        )
    elif statements.instant.get("Borrowings") is not None:
        metrics["total_debt"] = retrieved("total_debt", "Borrowings",
                                          statements.instant["Borrowings"])

    # EBIT = PBT + finance costs (Indian results report profit after finance cost)
    ebt, interest = metrics.get("ebt"), metrics.get("interest_expense")
    if ebt and ebt.value is not None and interest and interest.value is not None:
        metrics["ebit"] = calculated(
            "ebit", ebt.value + interest.value,
            "EBIT = Profit Before Tax + Finance Costs",
        )

    da = metrics.get("da") or metrics.get("da_cf")
    if da and da.value is not None and "ebit" in metrics:
        metrics.setdefault("da", da)
        metrics["ebitda"] = calculated("ebitda", metrics["ebit"].value + da.value,
                                       "EBITDA = EBIT + D&A")

    # capex from investing-activities purchase tags (reported as positive payments)
    capex_parts = [(tag, statements.flow[tag]) for tag in CAPEX_TAGS if tag in statements.flow]
    if capex_parts:
        total = sum(abs(v) for _, v in capex_parts)
        metrics["capex"] = calculated(
            "capex", total,
            "CapEx = " + " + ".join(f"|{tag}|" for tag, _ in capex_parts),
        )

    # shares outstanding from paid-up equity capital / face value
    paid_up = statements.instant.get(PAID_UP_TAG, statements.flow.get(PAID_UP_TAG))
    face = statements.instant.get(FACE_VALUE_TAG, statements.flow.get(FACE_VALUE_TAG))
    if paid_up and face and face > 0:
        metrics["shares_outstanding"] = calculated(
            "shares_outstanding", paid_up / face,
            f"Shares = Paid-up equity capital {paid_up:,.0f} / face value {face:,.2f}",
        )

    missing = [k for k in ("revenue", "ebit", "net_income") if k not in metrics]
    if missing:
        warnings.append(f"{period_label}: missing {', '.join(missing)} in the filed XBRL.")

    end_date = statements.period_end or filing.period_end
    return PeriodData(
        period=period_label, fiscal_year=filing.fiscal_year, end_date=end_date,
        period_type="annual", currency="INR", metrics=metrics,
    )


def _parse_bhavcopy(text: str, symbol: str) -> float | None:
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        clean = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
        if clean.get("SYMBOL") != symbol or clean.get("SERIES") not in LIQUID_SERIES:
            continue
        for field_name in ("CLOSE_PRICE", "LAST_PRICE", "AVG_PRICE"):
            raw = clean.get(field_name)
            if raw and raw not in ("-", ""):
                try:
                    return float(raw)
                except ValueError:
                    continue
    return None


def _missing_critical(periods: list[PeriodData]) -> list[str]:
    if not periods:
        return ["revenue", "ebit", "net_income", "total_debt", "cash", "shares_outstanding"]
    latest = periods[-1]
    critical = ["revenue", "ebit", "total_debt", "cash", "shares_outstanding"]
    return [k for k in critical if latest.value(k) is None]


def nse_peer_tickers() -> dict[str, list[str]]:
    """Curated NSE peer suggestions (a model choice; metrics are always fetched)."""
    return {
        "TCS": ["INFY", "HCLTECH", "WIPRO"],
        "INFY": ["TCS", "HCLTECH", "WIPRO"],
        "HCLTECH": ["TCS", "INFY", "WIPRO"],
        "WIPRO": ["TCS", "INFY", "HCLTECH"],
        "RELIANCE": ["ONGC", "IOC", "BPCL"],
        "ONGC": ["RELIANCE", "IOC", "BPCL"],
        "IOC": ["BPCL", "ONGC", "RELIANCE"],
        "HDFCBANK": ["ICICIBANK", "KOTAKBANK", "AXISBANK"],
        "ICICIBANK": ["HDFCBANK", "KOTAKBANK", "AXISBANK"],
        "KOTAKBANK": ["HDFCBANK", "ICICIBANK", "AXISBANK"],
        "SBIN": ["HDFCBANK", "ICICIBANK", "AXISBANK"],
        "AXISBANK": ["HDFCBANK", "ICICIBANK", "KOTAKBANK"],
        "ITC": ["HINDUNILVR", "NESTLEIND", "DABUR"],
        "HINDUNILVR": ["ITC", "NESTLEIND", "DABUR"],
        "NESTLEIND": ["HINDUNILVR", "ITC", "DABUR"],
        "MARUTI": ["M&M", "TATAMOTORS", "BAJAJ-AUTO"],
        "M&M": ["MARUTI", "TATAMOTORS", "BAJAJ-AUTO"],
        "TATAMOTORS": ["MARUTI", "M&M", "BAJAJ-AUTO"],
        "SUNPHARMA": ["DRREDDY", "CIPLA", "LUPIN"],
        "DRREDDY": ["SUNPHARMA", "CIPLA", "LUPIN"],
        "CIPLA": ["SUNPHARMA", "DRREDDY", "LUPIN"],
        "BHARTIARTL": ["RELIANCE", "IDEA", "TATACOMM"],
        "LT": ["SIEMENS", "ABB", "BHEL"],
        "ASIANPAINT": ["BERGEPAINT", "KANSAINER", "PIDILITIND"],
        "TITAN": ["ASIANPAINT", "DMART", "TRENT"],
        "BAJFINANCE": ["BAJAJFINSV", "CHOLAFIN", "SHRIRAMFIN"],
        "HINDALCO": ["VEDL", "TATASTEEL", "JSWSTEEL"],
        "TATASTEEL": ["JSWSTEEL", "HINDALCO", "VEDL"],
    }
