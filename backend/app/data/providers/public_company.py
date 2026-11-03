"""PublicCompanyProvider — composes keyless sources into one ProviderPayload.

    PublicCompanyProvider
      ├── SecEdgarProvider    income statement / balance sheet / cash flow (10-K)
      ├── YahooPriceProvider  share price, price history, regression beta
      └── FredRiskFreeProvider risk-free rate (10Y Treasury)

Any of these can be swapped or supplemented (e.g. an API-key provider) by
implementing DataProvider — the valuation engine never changes.
"""
from __future__ import annotations

import asyncio
import logging

from ...core.errors import ProviderError, TickerNotFoundError
from ...schemas.common import SourceRecord, SourceType, SourcedValue, Unit, ValueStatus
from ...schemas.company import CompanyInfo, PeriodData
from ...schemas.valuation import PeerMetrics
from .base import DataProvider, MarketSnapshot, ProviderPayload, HttpClient, today
from .fred import FredRiskFreeProvider
from .sec import SecEdgarProvider
from .yahoo import YahooPriceProvider

logger = logging.getLogger(__name__)

# Curated large-cap universes used only to SUGGEST peers (explicitly a model
# choice — every peer metric is still fetched live and attributed).
SUGGESTED_PEERS: dict[str, list[str]] = {
    "AAPL": ["MSFT", "GOOGL", "META"],
    "MSFT": ["AAPL", "GOOGL", "AMZN"],
    "GOOGL": ["MSFT", "META", "AMZN"],
    "AMZN": ["MSFT", "GOOGL", "META"],
    "META": ["GOOGL", "MSFT", "SNAP"],
    "NVDA": ["AMD", "AVGO", "QCOM"],
    "AMD": ["NVDA", "AVGO", "QCOM"],
    "TSLA": ["GM", "F", "RIVN"],
    "JPM": ["BAC", "WFC", "C"],
    "BAC": ["JPM", "WFC", "C"],
    "XOM": ["CVX", "COP", "EOG"],
    "CVX": ["XOM", "COP", "EOG"],
    "JNJ": ["PFE", "MRK", "ABBV"],
    "WMT": ["COST", "TGT", "KR"],
    "COST": ["WMT", "TGT", "BJ"],
    "UNH": ["CI", "CNC", "HUM"],
    "V": ["MA", "AXP", "PYPL"],
    "MA": ["V", "AXP", "PYPL"],
    "ORCL": ["IBM", "SAP", "CRM"],
    "CRM": ["NOW", "ORCL", "IBM"],
    "NFLX": ["DIS", "WBD", "PARA"],
    "KO": ["PEP", "MNST", "KDP"],
    "PEP": ["KO", "MNST", "KDP"],
    "DIS": ["NFLX", "WBD", "PARA"],
}

FINANCIAL_INDUSTRY_HINTS = ("bank", "credit", "insurance", "savings", "holding")


class PublicCompanyProvider(DataProvider):
    name = "public_company"
    kind = "public"

    def __init__(self) -> None:
        self.sec = SecEdgarProvider()
        self.yahoo = YahooPriceProvider()
        self.fred = FredRiskFreeProvider()
        self.http = HttpClient()

    async def fetch(self, ticker: str, include_comparables: bool = True,
                    peer_tickers: list[str] | None = None, **_) -> ProviderPayload:
        ticker = ticker.strip().upper()
        warnings: list[str] = []
        sources: list[SourceRecord] = []
        missing: list[str] = []

        # 1) Fundamentals from SEC EDGAR (required — this is the audit trail)
        sec_out = await self.sec.fetch(ticker)
        company: CompanyInfo = sec_out["company"]
        periods: list[PeriodData] = sec_out["periods"]
        sources.extend(sec_out["sources"])
        warnings.extend(sec_out["warnings"])
        missing.extend(sec_out["missing"])

        # 2) Market data: price, history, beta; 3) risk-free rate. Fail soft:
        # missing market inputs are flagged for the user, never guessed.
        market = MarketSnapshot()
        price_task = asyncio.create_task(self.yahoo.latest_price(ticker))
        beta_task = asyncio.create_task(self.yahoo.compute_beta(ticker))
        rf_task = asyncio.create_task(self.fred.latest_10y())
        hist_task = asyncio.create_task(self.yahoo.history(ticker, "2y"))

        for label, task in (("price", price_task), ("beta", beta_task),
                            ("risk-free rate", rf_task), ("price history", hist_task)):
            try:
                res = await task
            except Exception as exc:  # noqa: BLE001 — soft-fail per source
                warnings.append(f"Could not retrieve {label}: {getattr(exc, 'detail', exc)}")
                continue
            if label == "price":
                market.share_price = res["price"]
                market.price_currency = res["currency"]
                market.price_date = res["date"]
                if res.get("exchange"):
                    company.exchange = company.exchange or res["exchange"]
            elif label == "beta":
                market.beta = res["beta"]
                market.beta_r_squared = res["r_squared"]
                market.beta_observations = res["observations"]
                market.beta_source = (
                    f"OLS regression vs {res['benchmark']} — {res['window']}, "
                    f"n={res['observations']}, R2={res['r_squared']}"
                )
            elif label == "risk-free rate":
                market.risk_free_rate = res["rate"]
                market.risk_free_source = f"FRED DGS10 as of {res['as_of']} ({res['rate']:.2%})"
                sources.append(await self.fred.source_record())
            elif label == "price history":
                market.price_history = res["points"][-520:]  # cap payload ~2y

        # shares outstanding (SEC dei) -> market cap
        latest = periods[-1].metrics if periods else {}
        shares_sv = latest.get("shares_outstanding")
        if shares_sv and shares_sv.value:
            market.shares_outstanding = shares_sv.value
            if market.share_price:
                market.market_cap = market.share_price * market.shares_outstanding
        else:
            missing.append("shares_outstanding")
            warnings.append("Shares outstanding not reported in SEC filings — "
                            "add it on the Data Review page to compute per-share values.")

        if market.share_price is None:
            missing.append("share_price")
        if market.beta is None:
            missing.append("beta")
        if market.risk_free_rate is None:
            missing.append("risk_free_rate")

        if market.price_currency and market.price_currency != company.currency:
            warnings.append(
                f"Price currency ({market.price_currency}) differs from reporting currency "
                f"({company.currency}) — verify before computing market cap."
            )

        # market cap provenance
        if market.market_cap:
            sources.append(SourceRecord(
                id="market-cap", name="Market capitalisation (calculated)",
                source_type=SourceType.MODEL_CALCULATION, retrieved_at=today(),
                description="Market cap = latest close x shares outstanding (SEC dei:EntityCommonStockSharesOutstanding).",
                metrics=["market_cap"],
            ))
        sources.append(SourceRecord(
            id="yahoo-prices", name="Yahoo Finance daily price history",
            source_type=SourceType.PUBLIC_API,
            url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            retrieved_at=today(),
            description="Adjusted daily closes used for beta regression and the current price.",
            metrics=["share_price", "beta", "price_history"],
        ))

        # curated peer suggestions (labelled model choice, metrics fetched live)
        peer_list = [p.strip().upper() for p in (peer_tickers or []) if p.strip()]
        if include_comparables and not peer_list:
            peer_list = SUGGESTED_PEERS.get(ticker, [])
            if peer_list:
                warnings.append(
                    f"Suggested peers {', '.join(peer_list)} (curated universe) — "
                    "edit the peer list on the Comparables page."
                )

        return ProviderPayload(
            company=company, periods=periods, market=market, sources=sources,
            missing=sorted(set(missing)), warnings=warnings,
            preview=[{"peers": peer_list}],
        )

    # ---- comparables -------------------------------------------------------
    async def fetch_peer(self, ticker: str) -> tuple[PeerMetrics | None, list[str]]:
        """Fetch one peer's headline metrics. Tolerates partial failure."""
        warnings: list[str] = []
        try:
            sec_out = await self.sec.fetch(ticker)
        except Exception as exc:  # noqa: BLE001
            return None, [f"Peer {ticker}: fundamentals unavailable ({getattr(exc, 'detail', exc)})"]
        periods = sec_out["periods"]
        if not periods:
            return None, [f"Peer {ticker}: no annual statements found"]
        latest = periods[-1]
        g = latest.value
        revenue, ebit, ni = g("revenue"), g("ebit"), g("net_income")
        ebitda = g("ebitda") or ((ebit + g("da")) if ebit is not None and g("da") is not None else None)
        cash, debt = g("cash") or 0.0, g("total_debt") or 0.0

        price = beta = None
        try:
            p = await self.yahoo.latest_price(ticker)
            price = p["price"]
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Peer {ticker}: price unavailable ({getattr(exc, 'detail', exc)})")
        try:
            b = await self.yahoo.compute_beta(ticker)
            beta = b["beta"]
        except Exception:
            beta = None
        shares = g("shares_outstanding")
        mcap = price * shares if price and shares else None
        ev = mcap + debt - cash if mcap is not None else None

        pm = PeerMetrics(
            ticker=ticker, name=sec_out["company"].name, currency=latest.currency,
            ev=ev, revenue=revenue, ebitda=ebitda, ebit=ebit, net_income=ni,
            market_cap=mcap,
            ev_revenue=(ev / revenue) if ev and revenue else None,
            ev_ebitda=(ev / ebitda) if ev and ebitda else None,
            ev_ebit=(ev / ebit) if ev and ebit else None,
            pe=(mcap / ni) if mcap and ni and ni > 0 else None,
            levered_beta=beta,
            source="SEC EDGAR (statements) + Yahoo Finance (price, beta)",
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={ticker}",
            retrieved_at=today(),
            note=f"Fiscal period {latest.period}",
        )
        return pm, warnings
