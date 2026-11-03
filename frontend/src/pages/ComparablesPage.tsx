/** COMPARABLES — peer multiples vs DCF; skipped honestly when peer data is thin. */
import { ContextLabel, SectionHeader, SourceBadge } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct, tipFor } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function ComparablesPage() {
  const { view } = useValuation();
  const c = view?.comparables;

  if (!c) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">Comparables not run — enable them when running the valuation.</div>;
  }

  if (c.status === "insufficient_data") {
    return (
      <div>
        <SectionHeader title="Comparable Valuation" subtitle="Skipped — no multiples were invented." />
        <div className="panel px-5 py-6">
          <ul className="space-y-2 text-[13px] text-muted">
            {c.notes.map((n, i) => <li key={i}>⚠ {n}</li>)}
          </ul>
          <p className="mt-4 text-[12px] text-dim">
            Provide peer tickers when running the valuation (Mode B) to enable comparable-company analysis.
          </p>
        </div>
      </div>
    );
  }

  const stats = Object.entries(c.multiple_stats);

  return (
    <div>
      <SectionHeader
        title="Comparable Valuation"
        subtitle="What similar companies are worth today — used as a reality check against the DCF, never a replacement for it."
        right={
          c.dcf_vs_comps ? (
            <span className="num text-[13px] text-muted">
              DCF {fmtMoney(c.dcf_vs_comps.dcf_price, "$", 2)} vs comps {fmtMoney(c.dcf_vs_comps.comps_median_price, "$", 2)}
            </span>
          ) : undefined
        }
      />

      <ContextLabel
        items={[
          { k: "Whose peers", v: (view?.options?.peer_tickers ?? []).length ? (view?.options?.peer_tickers ?? []).join(", ") : "suggested peer set" },
          { k: "Compared with", v: view?.company ? `our DCF value for ${view.company.name} ↔ median multiples of those peers` : "the DCF value" },
          { k: "Rule", v: "peer multiples inform — they never overwrite the DCF" },
        ]}
      />

      {c.dcf_vs_comps && (
        <div className="mb-5 border border-line bg-ink-900 px-4 py-3">
          <div className="micro">DCF vs comparable valuation</div>
          <p className="mt-1.5 text-[13px] text-[#dfe3ea]">{c.dcf_vs_comps.commentary}</p>
        </div>
      )}

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map(([name, s]) => (
          <div key={name} className="panel px-4 py-3">
            <div className="micro">{name}</div>
            <div className="num mt-1.5 text-[18px] text-white">{s.median != null ? `${fmtNum(s.median)}x` : "—"}</div>
            <div className="mt-1 text-[11px] text-dim">median of {s.count} peers · mean {s.mean != null ? `${fmtNum(s.mean)}x` : "—"}</div>
          </div>
        ))}
      </div>

      <div className="panel overflow-x-auto mb-5">
        <div className="panel-header">
          <span className="micro">Peer metrics</span>
          <span className="text-[10px] text-dim">SEC EDGAR statements + market prices</span>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Ticker", "Name", "Market cap", "EV", "Revenue", "EBITDA", "Net income",
                "EV/Rev", "EV/EBITDA", "EV/EBIT", "P/E", "Levered β", "Source"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {c.peers.map((p) => (
              <tr key={p.ticker} className="row-hover">
                <td className="num px-3 py-1.5 text-[12px] text-accent">{p.ticker}</td>
                <td className="px-3 py-1.5 text-[12px] text-[#dfe3ea] max-w-[160px] truncate">{p.name ?? "—"}</td>
                <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(p.market_cap)}</td>
                <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(p.ev)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(p.revenue)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(p.ebitda)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(p.net_income)}</td>
                <td className="num px-3 py-1.5 text-[12px]">{p.ev_revenue ? `${fmtNum(p.ev_revenue)}x` : "—"}</td>
                <td className="num px-3 py-1.5 text-[12px]">{p.ev_ebitda ? `${fmtNum(p.ev_ebitda)}x` : "—"}</td>
                <td className="num px-3 py-1.5 text-[12px]">{p.ev_ebit ? `${fmtNum(p.ev_ebit)}x` : "—"}</td>
                <td className="num px-3 py-1.5 text-[12px]">{p.pe ? `${fmtNum(p.pe)}x` : "—"}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtNum(p.levered_beta)}</td>
                <td className="px-3 py-1.5"><SourceBadge type="PUBLIC_API" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {c.implied_values.length > 0 && (
        <div className="panel overflow-x-auto mb-5">
          <div className="panel-header"><span className="micro">Implied values from peer medians</span></div>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-line">
                {["Multiple", "Peer median", "Subject metric", "Implied EV", "Implied equity", "Implied price", "vs DCF"].map((h) => (
                  <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {c.implied_values.map((r) => (
                <tr key={r.multiple} className="row-hover">
                  <td className="px-3 py-1.5 text-[12.5px] text-[#dfe3ea]">{r.multiple}</td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtNum(r.peer_median)}x</td>
                  <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(r.subject_metric)}</td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(r.implied_ev)}</td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(r.implied_equity)}</td>
                  <td className="num px-3 py-1.5 text-[12px] text-white">{fmtMoney(r.implied_price, "$", 2)}</td>
                  <td className={`num px-3 py-1.5 text-[12px] ${(r.vs_dcf ?? 0) >= 0 ? "text-up" : "text-down"}`}>
                    {r.vs_dcf != null ? fmtPct(r.vs_dcf) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ul className="space-y-1 text-[11.5px] text-dim">
        {c.notes.map((n, i) => <li key={i}>• {n}</li>)}
      </ul>
    </div>
  );
}
