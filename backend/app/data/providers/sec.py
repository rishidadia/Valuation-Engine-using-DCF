"""SEC EDGAR provider — keyless US public-company fundamentals (XBRL companyfacts).

Docs: https://www.sec.gov/edgar/sec-api-documentation
Every value keeps its concept name, form, and filing URL for traceability.
"""
from __future__ import annotations

import re
from datetime import date

from ...core.config import settings
from ...core.errors import ProviderError, TickerNotFoundError
from ...schemas.common import SourceRecord, SourceType, SourcedValue, Unit, ValueStatus
from ...schemas.company import CompanyInfo, PeriodData
from .base import HttpClient, today

# us-gaap concept alternatives, in priority order
CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "operating_expenses": ["OperatingExpenses"],
    "ebit": ["OperatingIncomeLoss"],
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
        # JPM retagged total interest expense as InterestExpenseOperating (FY24+);
        # fills only years the higher-priority concepts do not cover.
        "InterestExpenseOperating",
    ],
    "income_tax_expense": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "ebt": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "da": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "DepreciationNonproduction",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "short_term_debt": [
        "ShortTermBorrowings", "OtherShortTermBorrowings", "LinesOfCreditCurrent",
        "DebtCurrent",
    ],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermNotesPayable"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "accounts_receivable": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "inventory": ["InventoryNet"],
    "accounts_payable": ["AccountsPayableCurrent", "AccountsPayableTradeCurrent"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}

INSTANT_KEYS = {
    "cash", "short_term_debt", "long_term_debt", "current_assets", "current_liabilities",
    "accounts_receivable", "inventory", "accounts_payable", "total_assets",
    "total_liabilities", "shareholders_equity",
}

DURATION_KEYS = set(CONCEPT_MAP) - INSTANT_KEYS

SEC_HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}


class SecEdgarProvider:
    """Fetches annual financial statements from SEC XBRL companyfacts."""

    name = "sec_edgar"

    def __init__(self) -> None:
        self.http = HttpClient(headers=SEC_HEADERS)
        self._tickers_cache: dict | None = None

    # -- ticker -> CIK ------------------------------------------------------
    async def resolve_ticker(self, ticker: str) -> dict:
        ticker = ticker.strip().upper()
        if self._tickers_cache is None:
            data = await self.http.json(settings.sec_company_tickers_url)
            self._tickers_cache = {str(v["ticker"]).upper(): v for v in data.values()}
        hit = self._tickers_cache.get(ticker)
        if not hit:
            raise TickerNotFoundError(
                f"No SEC-registered company with ticker '{ticker}'.",
                hint="Check the symbol (US tickers only, e.g. AAPL, MSFT, NVDA). "
                     "Private companies should use Excel upload instead.",
            )
        return hit

    # -- company facts -------------------------------------------------------
    async def company_facts(self, cik: int) -> dict:
        url = settings.sec_company_facts_url.format(cik=cik)
        return await self.http.json(url)

    async def submissions(self, cik: int) -> dict:
        """Company submissions: industry (SIC), exchanges, official name."""
        url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        return await self.http.json(url)

    async def profile(self, ticker: str) -> tuple[dict, dict]:
        hit = await self.resolve_ticker(ticker)
        facts = await self.company_facts(hit["cik_str"])
        return hit, facts

    @staticmethod
    def _annual_facts(concept: dict, instant: bool) -> dict[int, dict]:
        """Pick one annual (10-K) fact per fiscal year.

        Duration concepts: form 10-K, period >= 300 days.
        Instant concepts: form 10-K, no start date.
        """
        out: dict[int, dict] = {}
        for unit_facts in concept.get("units", {}).values():
            for f in unit_facts:
                if f.get("form") != "10-K":
                    continue
                end = f.get("end")
                if not end:
                    continue
                year = int(str(end)[:4])
                if instant:
                    if f.get("start"):
                        continue
                else:
                    start = f.get("start")
                    if not start:
                        continue
                    d0 = date.fromisoformat(start)
                    d1 = date.fromisoformat(end)
                    if (d1 - d0).days < 300:
                        continue
                # keep the last-filed fact for each fiscal year
                prev = out.get(year)
                if prev is None or str(f.get("filed", "")) >= str(prev.get("filed", "")):
                    out[year] = f
        return out

    def _pick_concept(self, facts: dict, key: str) -> tuple[str, dict] | None:
        gaap = facts.get("facts", {}).get("us-gaap", {})
        for concept_name in CONCEPT_MAP[key]:
            c = gaap.get(concept_name)
            if not c:
                continue
            annual = self._annual_facts(c, instant=key in INSTANT_KEYS)
            if annual:
                return concept_name, {"unit": _first_unit(c), "by_year": annual}
        return None

    # Fallback components for D&A: some filers (MSFT uses a company extension
    # tag, GOOGL reports only Depreciation) never tag a combined us-gaap D&A
    # concept. Without these components `da` — and with it EBITDA and da_pct —
    # would be missing for such companies and the forecast could not run.
    DA_COMPONENTS = ("Depreciation", "AmortizationOfIntangibleAssets")

    def _fill_da_components(
        self,
        by_year: dict[int, dict[str, SourcedValue]],
        facts: dict,
        currency: str,
        prov: list[dict],
        warnings: list[str],
    ) -> None:
        """Fill missing `da` values by summing the filer's component tags.

        The sum keeps full provenance: the source names the exact us-gaap
        concepts used and the provenance list records them per year, so every
        value remains traceable to filed facts (never invented).
        """
        if not by_year or all("da" in m for m in by_year.values()):
            return
        gaap = facts.get("facts", {}).get("us-gaap", {})
        components: dict[str, dict[int, dict]] = {}
        for concept_name in self.DA_COMPONENTS:
            c = gaap.get(concept_name)
            if c:
                annual = self._annual_facts(c, instant=False)
                if annual:
                    components[concept_name] = annual
        if not components:
            warnings.append(
                "Depreciation/amortization is not tagged by this filer — "
                "D&A cannot be derived from filings; provide it on the Assumptions page."
            )
            return
        for year, metrics in by_year.items():
            if "da" in metrics:
                continue
            total, used, first_fact = 0.0, [], None
            for concept_name, annual in components.items():
                f = annual.get(year)
                if not f or f.get("val") is None:
                    continue
                if first_fact is None:
                    first_fact = f
                total += float(f["val"])
                used.append(concept_name)
            if not used:
                continue
            metrics["da"] = SourcedValue(
                value=total, unit=Unit.CURRENCY, currency=currency,
                period=f"FY{year}", source_type=SourceType.PUBLIC_API,
                source=f"SEC EDGAR XBRL {' + '.join(used)} (sum)",
                source_url=_filing_url(first_fact), retrieved_at=today(),
                status=ValueStatus.RETRIEVED,
                note=("Combined D&A concept not tagged — sum of reported components; "
                      f"form {first_fact.get('form')} filed {first_fact.get('filed')}"),
                original_value=total,
            )
            prov.append({"key": "da", "year": year, "concept": " + ".join(used)})

    def extract_periods(self, facts: dict, currency: str) -> tuple[list[PeriodData], list[str], list[dict]]:
        """Build normalized annual periods; returns (periods, warnings, provenance)."""
        warnings: list[str] = []
        prov: list[dict] = []
        by_year: dict[int, dict[str, SourcedValue]] = {}

        gaap = facts.get("facts", {}).get("us-gaap", {})
        for key in list(CONCEPT_MAP):
            # Try every candidate concept, in priority order: a filer may switch
            # tags across years (e.g. Alphabet reports FY2025 under `Revenues`
            # but earlier years under the customer-contract concept), so the
            # first hit must not cut off the remaining years.
            for concept_name in CONCEPT_MAP[key]:
                c = gaap.get(concept_name)
                if not c:
                    continue
                for year, f in self._annual_facts(c, instant=key in INSTANT_KEYS).items():
                    if key in by_year.get(year, {}):
                        continue  # a higher-priority concept already covers this year
                    val = f.get("val")
                    if val is None:
                        continue
                    sv = SourcedValue(
                        value=float(val),
                        unit=Unit.COUNT if key == "shares_outstanding" else Unit.CURRENCY,
                        currency=currency,
                        period=f"FY{year}",
                        source_type=SourceType.PUBLIC_API,
                        source=f"SEC EDGAR XBRL {concept_name}",
                        source_url=_filing_url(f),
                        retrieved_at=today(),
                        status=ValueStatus.RETRIEVED,
                        note=f"form {f.get('form')} filed {f.get('filed')}",
                        original_value=float(val),
                    )
                    by_year.setdefault(year, {})[key] = sv
                    prov.append({"key": key, "year": year, "concept": concept_name})

        # D&A split into components (MSFT, GOOGL, …) — fill it before deriving
        self._fill_da_components(by_year, facts, currency, prov, warnings)

        # shares outstanding (dei, latest)
        dei = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding")
        latest_shares: tuple[int, dict] | None = None
        if dei:
            for unit_facts in dei.get("units", {}).values():
                for f in unit_facts:
                    if not f.get("end"):
                        continue
                    year = int(str(f["end"])[:4])
                    if latest_shares is None or str(f.get("filed", "")) >= str(latest_shares[1].get("filed", "")):
                        latest_shares = (year, f)
        if latest_shares:
            year, f = latest_shares
            sv = SourcedValue(
                value=float(f["val"]), unit=Unit.COUNT, period=f"FY{year}",
                source_type=SourceType.PUBLIC_API,
                source="SEC EDGAR dei:EntityCommonStockSharesOutstanding",
                source_url=_filing_url(f), retrieved_at=today(),
                status=ValueStatus.RETRIEVED,
                note=f"shares outstanding as of {f.get('end')}",
            )
            target = max(by_year) if by_year else year
            by_year.setdefault(target, {})["shares_outstanding"] = sv
        elif by_year:
            # Some filers (e.g. Alphabet) never tag dei:EntityCommonStockSharesOutstanding.
            # Fall back to the us-gaap share concepts so market cap, EV multiples,
            # and implied share price stay computable — each value still traceable.
            for concept_name, instant in (
                ("CommonStockSharesOutstanding", True),
                ("WeightedAverageNumberOfDilutedSharesOutstanding", False),
            ):
                c = gaap.get(concept_name)
                if not c:
                    continue
                annual = self._annual_facts(c, instant=instant)
                if not annual:
                    continue
                year, f = max(annual.items())
                sv = SourcedValue(
                    value=float(f["val"]), unit=Unit.COUNT, period=f"FY{year}",
                    source_type=SourceType.PUBLIC_API,
                    source=f"SEC EDGAR XBRL {concept_name}",
                    source_url=_filing_url(f), retrieved_at=today(),
                    status=ValueStatus.RETRIEVED,
                    note=("dei tag absent — " + (
                        f"total shares outstanding as of {f.get('end')}"
                        if instant else
                        f"diluted weighted-average shares, form {f.get('form')} filed {f.get('filed')}")),
                )
                target = max(by_year)
                by_year.setdefault(target, {})["shares_outstanding"] = sv
                prov.append({"key": "shares_outstanding", "year": target,
                             "concept": concept_name})
                break

        if not by_year:
            return [], ["SEC EDGAR returned no annual facts for this company."], prov

        periods: list[PeriodData] = []
        for year in sorted(by_year):
            metrics = by_year[year]
            # derived fields — clearly marked as calculations
            _derive(metrics, year, currency)
            periods.append(PeriodData(
                period=f"FY{year}", fiscal_year=year, end_date=date(year, 12, 31),
                period_type="annual", currency=currency, metrics=metrics,
            ))

        # Keep the most recent 8 fiscal years — deep history predates the
        # current XBRL taxonomy and produces spurious "missing revenue" noise.
        periods = periods[-8:]
        for p in periods:
            missing = [k for k in ("revenue", "ebit", "net_income")
                       if p.value(k) is None]
            if missing:
                warnings.append(f"{p.period}: missing {', '.join(missing)} on income statement.")
        return periods, warnings, prov

    async def fetch(self, ticker: str, **_) -> dict:
        hit, facts = await self.profile(ticker)
        entity = facts.get("entityName", hit["title"])
        industry = None
        sic = None
        exchanges = None
        try:
            subs = await self.submissions(hit["cik_str"])
            industry = subs.get("sicDescription")
            sic = subs.get("sic")
            exchanges = (subs.get("exchanges") or [None])[0]
        except ProviderError:
            pass  # industry is enrichment, not a required financial input
        currency = "USD"
        periods, warnings, prov = self.extract_periods(facts, currency)
        company = CompanyInfo(
            name=entity, ticker=hit["ticker"].upper(), cik=f"{hit['cik_str']:010d}",
            currency=currency, is_public=True,
            industry=industry, sic_code=str(sic) if sic else None, exchange=exchanges,
            source_type=SourceType.PUBLIC_API, source="SEC EDGAR",
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={hit['cik_str']:010d}",
            retrieved_at=today(), provider=self.name,
        )
        source = SourceRecord(
            id="sec-edgar", name="SEC EDGAR XBRL company facts",
            source_type=SourceType.PUBLIC_API,
            url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{hit['cik_str']:010d}.json",
            retrieved_at=today(),
            description="Audited annual financial statements as filed with the US SEC (10-K).",
            metrics=sorted({p["key"] for p in prov}),
        )
        missing = _missing_critical(periods)
        return {
            "company": company, "periods": periods, "sources": [source],
            "missing": missing, "warnings": warnings, "provenance": prov,
        }


def _first_unit(concept: dict) -> str:
    return next(iter(concept.get("units", {}).keys()), "USD")


def _filing_url(f: dict) -> str | None:
    accn = f.get("accn")
    cik = f.get("cik")
    if accn and cik:
        return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{str(accn).replace('-', '')}/{accn}-index.htm")
    return "https://www.sec.gov/edgar/search/"


def _derive(metrics: dict[str, SourcedValue], year: int, currency: str) -> None:
    """Derivable income-statement fields, labelled MODEL_CALCULATION with formula."""
    period = f"FY{year}"

    def calc(key: str, value: float, formula: str) -> None:
        metrics[key] = SourcedValue(
            value=value, unit=Unit.CURRENCY, currency=currency, period=period,
            source_type=SourceType.MODEL_CALCULATION,
            source="Derived from reported SEC values", retrieved_at=today(),
            status=ValueStatus.CALCULATED, note=formula,
        )

    g = lambda k: metrics[k].value if k in metrics and metrics[k].value is not None else None
    rev, cogs, gp, ebit, da = g("revenue"), g("cogs"), g("gross_profit"), g("ebit"), g("da")
    if gp is None and rev is not None and cogs is not None:
        calc("gross_profit", rev - cogs, "Gross Profit = Revenue - COGS")
    if ebit is None and gp is not None and "operating_expenses" in metrics and metrics["operating_expenses"].value is not None:
        calc("ebit", gp - metrics["operating_expenses"].value, "EBIT = Gross Profit - Operating Expenses")
        ebit = g("ebit")
    ni, tax = g("net_income"), g("income_tax_expense")
    ebt = g("ebt")
    if ebt is None and ni is not None and tax is not None:
        calc("ebt", ni + tax, "EBT = Net Income + Income Tax Expense")
        ebt = g("ebt")
    # Operating income not tagged (JPM-style banks tag none at all; JNJ stopped
    # tagging it after FY2014) — reconstruct EBIT from pre-tax income so the
    # ebit_margin driver stays derivable. When interest expense exceeds 20% of
    # revenue the filer reports revenue NET of interest, so no add-back is made;
    # otherwise the standard EBIT = EBT + interest expense applies. Every path
    # is labelled — nothing is invented silently.
    if ebit is None and ebt is not None:
        interest, revenue = g("interest_expense"), g("revenue")
        if (interest is not None and revenue not in (None, 0)
                and abs(interest) / abs(revenue) > 0.20):
            calc("ebit", ebt,
                 "EBIT ≈ EBT (revenue reported net of interest expense — interest "
                 "exceeds 20% of revenue, so no add-back; operating income concept "
                 "not tagged by this filer)")
        elif interest is not None:
            calc("ebit", ebt + abs(interest),
                 "EBIT = EBT + Interest Expense (operating income concept not "
                 "tagged by this filer)")
        else:
            calc("ebit", ebt,
                 "EBIT ≈ EBT (operating income and interest expense not tagged — "
                 "pre-tax income used as the closest filed measure)")
        ebit = g("ebit")
    if da is None:
        da = g("da_cf")
    if "ebitda" not in metrics and ebit is not None and da is not None:
        calc("ebitda", ebit + da, "EBITDA = EBIT + D&A")
    # total debt
    if "total_debt" not in metrics:
        st, lt = g("short_term_debt"), g("long_term_debt")
        if st is not None or lt is not None:
            calc("total_debt", (st or 0.0) + (lt or 0.0), "Total Debt = Short-Term Debt + Long-Term Debt")


def _missing_critical(periods: list[PeriodData]) -> list[str]:
    if not periods:
        return ["revenue", "ebit", "net_income", "total_debt", "cash", "shares_outstanding"]
    latest = periods[-1]
    critical = ["revenue", "ebit", "total_debt", "cash", "shares_outstanding"]
    return [k for k in critical if latest.value(k) is None]
