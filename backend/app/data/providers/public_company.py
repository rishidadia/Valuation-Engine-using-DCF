"""PublicCompanyProvider — composes keyless sources into one ProviderPayload.

    PublicCompanyProvider
      ├── SecEdgarProvider    income statement / balance sheet / cash flow (10-K)   [US]
      ├── YahooPriceProvider  share price, price history, regression beta           [US]
      ├── NseIndiaProvider    annual XBRL filings, bhavcopy closes, NIFTY beta      [IN]
      ├── KiteMarketProvider  optional prices/beta for NSE names (Zerodha Kite)
      └── FredRiskFreeProvider risk-free rate (US 10Y Treasury / India 10Y G-Sec)

Any of these can be swapped or supplemented by implementing DataProvider — the
valuation engine never changes.
"""
from __future__ import annotations

import asyncio
import logging

from ...core.config import settings
from ...core.errors import ProviderError, TickerNotFoundError
from ...schemas.common import SourceRecord, SourceType, SourcedValue, Unit, ValueStatus
from ...schemas.company import CompanyInfo, PeriodData
from ...schemas.valuation import PeerMetrics
from .base import DataProvider, MarketSnapshot, ProviderPayload, HttpClient, today
from .fred import FredRiskFreeProvider
from .kite import KiteMarketProvider
from .nse import NseIndiaProvider, nse_peer_tickers
from .sec import SecEdgarProvider
from .yahoo import YahooPriceProvider

logger = logging.getLogger(__name__)

MARKET_US = "US"
MARKET_IN = "IN"
NSE_SUFFIXES = (".NS", ".NSE", ".NSEI")

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


def resolve_market(ticker: str, market: str | None = None) -> tuple[str, str]:
    """Return ``(symbol, market)``; an explicit market wins over the suffix.

    ``RELIANCE.NS`` is an NSE symbol; ``RELIANCE.BO`` is BSE-only and unsupported.
    Anything else defaults to the US (SEC EDGAR) path, so existing behaviour is
    unchanged.
    """
    raw = (ticker or "").strip().upper()
    if not raw:
        raise TickerNotFoundError("A ticker symbol is required.")
    if raw.endswith(".BO"):
        raise ProviderError(
            "BSE-only symbols are not supported — this project uses NSE data.",
            hint="Use the same company's NSE symbol (e.g. RELIANCE, not RELIANCE.BO).",
        )
    for suffix in NSE_SUFFIXES:
        if raw.endswith(suffix):
            return raw[: -len(suffix)].strip(), MARKET_IN
    if (market or "").strip().upper() in {"IN", "INDIA", "NSE"}:
        return raw, MARKET_IN
    return raw, MARKET_US


class PublicCompanyProvider(DataProvider):
    name = "public_company"
    kind = "public"

    def __init__(self) -> None:
        self.sec = SecEdgarProvider()
        self.yahoo = YahooPriceProvider()
        self.nse = NseIndiaProvider()
        self.fred = FredRiskFreeProvider()
        self.http = HttpClient()

    async def fetch(self, ticker: str, include_comparables: bool = True,
                    peer_tickers: list[str] | None = None, market: str | None = None,
                    **_) -> ProviderPayload:
        symbol, resolved = resolve_market(ticker, market)
        if resolved == MARKET_IN:
            return await self._fetch_india(symbol, include_comparables, peer_tickers)
        ticker = symbol
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
        market_snapshot = MarketSnapshot(market=MARKET_US)
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
                market_snapshot.share_price = res["price"]
                market_snapshot.price_currency = res["currency"]
                market_snapshot.price_date = res["date"]
                market_snapshot.price_provider = "Yahoo Finance latest close"
                if res.get("exchange"):
                    company.exchange = company.exchange or res["exchange"]
            elif label == "beta":
                market_snapshot.beta = res["beta"]
                market_snapshot.beta_r_squared = res["r_squared"]
                market_snapshot.beta_observations = res["observations"]
                market_snapshot.beta_provider = "Yahoo Finance price history (OLS vs SPY)"
                market_snapshot.beta_source = (
                    f"OLS regression vs {res['benchmark']} — {res['window']}, "
                    f"n={res['observations']}, R2={res['r_squared']}"
                )
            elif label == "risk-free rate":
                market_snapshot.risk_free_rate = res["rate"]
                market_snapshot.risk_free_source = f"FRED DGS10 as of {res['as_of']} ({res['rate']:.2%})"
                sources.append(await self.fred.source_record())
            elif label == "price history":
                market_snapshot.price_history = res["points"][-520:]  # cap payload ~2y

        # shares outstanding (SEC dei) -> market cap
        latest = periods[-1].metrics if periods else {}
        shares_sv = latest.get("shares_outstanding")
        if shares_sv and shares_sv.value:
            market_snapshot.shares_outstanding = shares_sv.value
            market_snapshot.shares_provider = "SEC EDGAR dei:EntityCommonStockSharesOutstanding"
            if market_snapshot.share_price:
                market_snapshot.market_cap = market_snapshot.share_price * market_snapshot.shares_outstanding
        else:
            missing.append("shares_outstanding")
            warnings.append("Shares outstanding not reported in SEC filings — "
                            "add it on the Data Review page to compute per-share values.")

        if market_snapshot.share_price is None:
            missing.append("share_price")
        if market_snapshot.beta is None:
            missing.append("beta")
        if market_snapshot.risk_free_rate is None:
            missing.append("risk_free_rate")

        if market_snapshot.price_currency and market_snapshot.price_currency != company.currency:
            warnings.append(
                f"Price currency ({market_snapshot.price_currency}) differs from reporting currency "
                f"({company.currency}) — verify before computing market cap."
            )

        # market cap provenance
        if market_snapshot.market_cap:
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
            company=company, periods=periods, market=market_snapshot, sources=sources,
            missing=sorted(set(missing)), warnings=warnings,
            preview=[{"peers": peer_list}],
        )

    # ---- India / NSE -------------------------------------------------------
    async def _fetch_india(self, ticker: str, include_comparables: bool,
                           peer_tickers: list[str] | None) -> ProviderPayload:
        """NSE fundamentals (XBRL) + NSE or Kite market data, all in INR."""
        statements = await self.nse.fetch(ticker)
        company: CompanyInfo = statements["company"]
        periods: list[PeriodData] = statements["periods"]
        sources: list[SourceRecord] = list(statements["sources"])
        warnings: list[str] = list(statements["warnings"])
        missing: list[str] = list(statements["missing"])

        market_snapshot = MarketSnapshot(market=MARKET_IN, price_currency="INR")
        kite = KiteMarketProvider()
        use_kite = kite.available
        quote_url = f"https://www.nseindia.com/get-quotes/equity?symbol={ticker}"

        price_res, beta_res, rf_res = await asyncio.gather(
            kite.latest_price(ticker) if use_kite else self.nse.latest_quote(ticker),
            kite.compute_beta(ticker) if use_kite else self.nse.compute_beta(ticker),
            self.fred.latest_india_10y(),
            return_exceptions=True,
        )

        if isinstance(price_res, Exception):
            warnings.append(f"Could not retrieve price: {getattr(price_res, 'detail', price_res)}")
        else:
            market_snapshot.share_price = price_res["price"]
            market_snapshot.price_currency = price_res.get("currency") or "INR"
            market_snapshot.price_date = price_res["date"]
            market_snapshot.price_provider = (
                "Zerodha Kite Connect (last traded price)" if use_kite
                else "NSE India (official bhavcopy close)"
            )
            market_snapshot.price_source_url = quote_url
            sources.append(SourceRecord(
                id="nse-price",
                name=("Zerodha Kite Connect quote" if use_kite
                      else "NSE India daily bhavcopy (sec_bhavdata_full)"),
                source_type=SourceType.PUBLIC_API,
                url=quote_url if use_kite else "https://www.nseindia.com/all-reports",
                retrieved_at=today(),
                description=("Last traded price on NSE." if use_kite else
                             "Official NSE closing price from the published daily bhavcopy CSV."),
                metrics=["share_price"],
            ))

        if isinstance(beta_res, Exception):
            warnings.append(f"Could not retrieve beta: {getattr(beta_res, 'detail', beta_res)}")
        else:
            market_snapshot.beta = beta_res["beta"]
            market_snapshot.beta_r_squared = beta_res["r_squared"]
            market_snapshot.beta_observations = beta_res["observations"]
            market_snapshot.beta_provider = (
                "Zerodha Kite Connect (daily closes vs NIFTY 50)" if use_kite
                else "NSE India (month-end bhavcopy closes vs NIFTY 50)"
            )
            market_snapshot.beta_source_url = quote_url
            market_snapshot.beta_source = (
                f"OLS regression vs {beta_res['benchmark']} — {beta_res['window']}, "
                f"n={beta_res['observations']}, R2={beta_res['r_squared']}"
            )
            if not use_kite:
                sources.append(SourceRecord(
                    id="nse-nifty50-history",
                    name=f"NSE India {settings.nse_benchmark_index} index history",
                    source_type=SourceType.PUBLIC_API,
                    url="https://www.nseindia.com/reports-indices-historical-index-data",
                    retrieved_at=today(),
                    description=("Official NSE index history, used as the market benchmark "
                                 "for the beta regression."),
                    metrics=["beta"],
                ))

        if isinstance(rf_res, Exception):
            market_snapshot.risk_free_rate = settings.india_risk_free_fallback
            market_snapshot.risk_free_source = (
                f"Model default {settings.india_risk_free_fallback:.2%} — India 10Y G-Sec "
                "provider unavailable"
            )
            market_snapshot.risk_free_is_estimate = True
            warnings.append(
                "India 10-year G-Sec yield could not be retrieved — a labelled model "
                "default is used. Override the risk-free rate on the Assumptions page."
            )
        else:
            market_snapshot.risk_free_rate = rf_res["rate"]
            market_snapshot.risk_free_source = (
                f"FRED INDIRLTLT01STM (India 10Y G-Sec) as of {rf_res['as_of']} "
                f"({rf_res['rate']:.2%})"
            )
            sources.append(SourceRecord(
                id="fred-india-10y",
                name=f"FRED INDIRLTLT01STM — India 10Y G-Sec ({rf_res['as_of']})",
                source_type=SourceType.PUBLIC_API,
                url="https://fred.stlouisfed.org/series/INDIRLTLT01STM",
                retrieved_at=today(),
                description=("Risk-free rate proxy for India: 10-year government bond yield "
                             "(monthly, OECD series republished by FRED)."),
                metrics=["risk_free_rate"],
            ))

        # shares outstanding (from NSE XBRL paid-up capital / face value) -> market cap
        latest = periods[-1].metrics if periods else {}
        shares_sv = latest.get("shares_outstanding")
        if shares_sv and shares_sv.value:
            market_snapshot.shares_outstanding = shares_sv.value
            market_snapshot.shares_provider = (
                "NSE India XBRL (paid-up equity capital / face value)"
            )
            if market_snapshot.share_price:
                market_snapshot.market_cap = (
                    market_snapshot.share_price * market_snapshot.shares_outstanding
                )
        else:
            missing.append("shares_outstanding")
            warnings.append("Shares outstanding not derivable from NSE filings — "
                            "add it on the Data Review page to compute per-share values.")

        if market_snapshot.share_price is None:
            missing.append("share_price")
        if market_snapshot.beta is None:
            missing.append("beta")
        if market_snapshot.risk_free_rate is None:
            missing.append("risk_free_rate")

        if market_snapshot.market_cap:
            sources.append(SourceRecord(
                id="market-cap", name="Market capitalisation (calculated)",
                source_type=SourceType.MODEL_CALCULATION, retrieved_at=today(),
                description="Market cap = latest NSE close x shares outstanding (NSE XBRL paid-up capital / face value).",
                metrics=["market_cap"],
            ))

        peer_list = [p.strip().upper() for p in (peer_tickers or []) if p.strip()]
        if include_comparables and not peer_list:
            peer_list = nse_peer_tickers().get(ticker, [])
            if peer_list:
                warnings.append(
                    f"Suggested NSE peers {', '.join(peer_list)} (curated universe) — "
                    "edit the peer list on the Comparables page."
                )

        return ProviderPayload(
            company=company, periods=periods, market=market_snapshot, sources=sources,
            missing=sorted(set(missing)), warnings=warnings,
            preview=[{"peers": peer_list}],
        )

    # ---- comparables -------------------------------------------------------
    async def fetch_peer(self, ticker: str, market: str | None = None) -> tuple[PeerMetrics | None, list[str]]:
        """Fetch one peer's headline metrics. Tolerates partial failure."""
        try:
            symbol, resolved = resolve_market(ticker, market)
        except ProviderError as exc:
            return None, [f"Peer {ticker}: {exc.detail}"]
        if resolved == MARKET_IN:
            return await self._fetch_india_peer(symbol)

        warnings: list[str] = []
        try:
            sec_out = await self.sec.fetch(symbol)
        except Exception as exc:  # noqa: BLE001
            return None, [f"Peer {symbol}: fundamentals unavailable ({getattr(exc, 'detail', exc)})"]
        periods = sec_out["periods"]
        if not periods:
            return None, [f"Peer {symbol}: no annual statements found"]

        price = beta = None
        try:
            p = await self.yahoo.latest_price(symbol)
            price = p["price"]
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Peer {symbol}: price unavailable ({getattr(exc, 'detail', exc)})")
        try:
            b = await self.yahoo.compute_beta(symbol)
            beta = b["beta"]
        except Exception:
            beta = None

        pm = _peer_metrics(
            symbol, sec_out["company"].name, periods, price, beta,
            source="SEC EDGAR (statements) + Yahoo Finance (price, beta)",
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={symbol}",
        )
        if pm is None:
            return None, [f"Peer {symbol}: no usable annual statement"]
        return pm, warnings

    async def _fetch_india_peer(self, symbol: str) -> tuple[PeerMetrics | None, list[str]]:
        warnings: list[str] = []
        try:
            statements = await self.nse.fetch(symbol, years=1)
        except Exception as exc:  # noqa: BLE001
            return None, [f"Peer {symbol}: NSE filings unavailable "
                          f"({getattr(exc, 'detail', exc)})"]
        periods = statements["periods"]
        if not periods:
            return None, [f"Peer {symbol}: no annual NSE filings found"]

        price = beta = None
        kite = KiteMarketProvider()
        try:
            quote = (await kite.latest_price(symbol)) if kite.available \
                else (await self.nse.latest_quote(symbol))
            price = quote["price"]
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Peer {symbol}: price unavailable ({getattr(exc, 'detail', exc)})")
        try:
            b = (await kite.compute_beta(symbol)) if kite.available \
                else (await self.nse.compute_beta(symbol))
            beta = b["beta"]
        except Exception:
            beta = None

        pm = _peer_metrics(
            symbol, statements["company"].name, periods, price, beta,
            source="NSE India (annual XBRL filings) + NSE/Kite market data",
            source_url=f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}",
        )
        if pm is None:
            return None, [f"Peer {symbol}: no usable annual statement"]
        return pm, warnings


def _peer_metrics(ticker: str, name: str, periods: list[PeriodData],
                  price: float | None, beta: float | None, *,
                  source: str, source_url: str) -> PeerMetrics | None:
    """Headline peer multiples from the latest annual period (USD or INR)."""
    if not periods:
        return None
    latest = periods[-1]
    g = latest.value
    revenue, ebit, ni = g("revenue"), g("ebit"), g("net_income")
    ebitda = g("ebitda") or ((ebit + g("da")) if ebit is not None and g("da") is not None else None)
    cash_v, debt_v = g("cash"), g("total_debt")
    cash, debt = cash_v or 0.0, debt_v or 0.0

    # Effective peer tax rate, used by the Hamada unlevering step instead of
    # silently borrowing the target company's rate.
    tax_expense, ebt = g("income_tax_expense"), g("ebt")
    peer_tax = None
    if tax_expense is not None and ebt not in (None, 0) and ebt > 0:
        candidate = abs(tax_expense) / ebt
        if 0 <= candidate <= 0.75:
            peer_tax = candidate

    shares = g("shares_outstanding")
    mcap = price * shares if price and shares else None
    ev = mcap + debt - cash if mcap is not None else None
    gross_de = (debt_v / mcap) if (debt_v is not None and mcap) else None

    return PeerMetrics(
        ticker=ticker, name=name, currency=latest.currency,
        ev=ev, revenue=revenue, ebitda=ebitda, ebit=ebit, net_income=ni,
        market_cap=mcap, total_debt=debt_v, cash=cash_v, tax_rate=peer_tax,
        debt_equity=gross_de,
        ev_revenue=(ev / revenue) if ev and revenue else None,
        ev_ebitda=(ev / ebitda) if ev and ebitda else None,
        ev_ebit=(ev / ebit) if ev and ebit else None,
        pe=(mcap / ni) if mcap and ni and ni > 0 else None,
        levered_beta=beta,
        source=source,
        source_url=source_url,
        retrieved_at=today(),
        note=f"Fiscal period {latest.period}",
    )
