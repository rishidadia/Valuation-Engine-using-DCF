"""Comparable valuation stage.

Never forces comps: if fewer than 2 peers have usable data the result is
`insufficient_data` with an explanation.
"""
from __future__ import annotations

import statistics

from ..schemas.company import PeriodData
from ..schemas.valuation import ComparablesResult, DcfResult, PeerMetrics

MIN_PEERS = 2


def _stats(values: list[float | None]) -> dict:
    clean = [v for v in values if v is not None and v == v]
    if not clean:
        return {"median": None, "mean": None, "count": 0}
    return {"median": statistics.median(clean), "mean": statistics.mean(clean), "count": len(clean)}


def build_comparables(
    peers: list[PeerMetrics],
    subject_periods: list[PeriodData],
    subject_price: float | None,
    subject_shares: float | None,
    dcf: DcfResult | None,
) -> ComparablesResult:
    notes: list[str] = []
    usable = [p for p in peers if (p.ev_revenue or p.ev_ebitda or p.ev_ebit or p.pe)]

    if len(usable) < MIN_PEERS:
        return ComparablesResult(
            status="insufficient_data",
            peers=peers,
            notes=[
                f"Comparable valuation skipped: only {len(usable)} peer(s) with usable "
                f"multiples (minimum {MIN_PEERS}).",
                "No peer multiples were assumed or invented.",
            ],
            dcf_vs_comps={"dcf_price": dcf.implied_share_price if dcf else None},
        )

    stats = {
        "EV/Revenue": _stats([p.ev_revenue for p in usable]),
        "EV/EBITDA": _stats([p.ev_ebitda for p in usable]),
        "EV/EBIT": _stats([p.ev_ebit for p in usable]),
        "P/E": _stats([p.pe for p in usable]),
    }
    notes.append(f"Multiples computed from {len(usable)} peers with retrievable market data.")

    latest = subject_periods[-1] if subject_periods else None
    subject = {}
    cash = debt = None
    if latest:
        g = latest.value
        revenue = g("revenue")
        ebit = g("ebit")
        da = g("da") if g("da") is not None else g("da_cf")
        ebitda = g("ebitda") or ((ebit + da) if ebit is not None and da is not None else None)
        ni = g("net_income")
        cash, debt = g("cash"), g("total_debt")
        subject = {"revenue": revenue, "ebitda": ebitda, "ebit": ebit, "net_income": ni}
    else:
        revenue = ebitda = ebit = ni = None

    mcap = subject_price * subject_shares if (subject_price and subject_shares) else None
    implied_rows: list[dict] = []

    def add(name: str, subject_metric: float | None, kind: str) -> None:
        med = stats[name]["median"]
        if not med or not subject_metric:
            return
        if kind == "ev":
            ev = med * subject_metric
            eq = ev + (cash or 0.0) - (debt or 0.0)
            price = eq / subject_shares if subject_shares else None
            implied_rows.append({
                "multiple": name, "peer_median": med, "subject_metric": subject_metric,
                "implied_ev": ev, "implied_equity": eq, "implied_price": price,
                "vs_dcf": ((price / dcf.implied_share_price - 1)
                           if price and dcf and dcf.implied_share_price else None),
            })
        else:
            if not mcap:
                return
            eq = med * subject_metric
            price = eq / subject_shares if subject_shares else None
            implied_rows.append({
                "multiple": name, "peer_median": med, "subject_metric": subject_metric,
                "implied_ev": None, "implied_equity": eq, "implied_price": price,
                "vs_dcf": ((price / dcf.implied_share_price - 1)
                           if price and dcf and dcf.implied_share_price else None),
            })

    add("EV/Revenue", revenue, "ev")
    add("EV/EBITDA", ebitda, "ev")
    add("EV/EBIT", ebit, "ev")
    add("P/E", ni, "equity")

    dcf_vs = None
    if dcf and dcf.implied_share_price and implied_rows:
        comps_prices = [r["implied_price"] for r in implied_rows if r["implied_price"]]
        if comps_prices:
            mid = statistics.median(comps_prices)
            dcf_vs = {
                "dcf_price": dcf.implied_share_price,
                "comps_median_price": mid,
                "spread": dcf.implied_share_price / mid - 1,
                "commentary": (
                    f"DCF implies {dcf.implied_share_price:,.2f} vs comps median "
                    f"{mid:,.2f} ({dcf.implied_share_price / mid - 1:+.1%})."
                ),
            }
            notes.append(dcf_vs["commentary"])

    return ComparablesResult(
        status="ok", peers=peers, multiple_stats=stats,
        implied_values=implied_rows,
        subject_metrics={k: v for k, v in subject.items() if v is not None},
        notes=notes, dcf_vs_comps=dcf_vs,
    )
