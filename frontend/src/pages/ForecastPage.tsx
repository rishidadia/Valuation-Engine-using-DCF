/** FORECAST — driver-based projection with historical comparison. */
import HistoryForecast from "../charts/HistoryForecast";
import { ContextLabel, SectionHeader } from "../components/ui";
import { fmtMoney, fmtPct, tipFor } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function ForecastPage() {
  const { view } = useValuation();
  if (!view?.forecast) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No forecast — run a valuation first.</div>;
  }
  const f = view.forecast;
  const hist = view.historical_periods;
  const histRows = view.historical?.rows ?? [];

  return (
    <div>
      <SectionHeader
        title="Forecast"
        subtitle={`${f.years.length} years ahead, built from the company's own history and your assumptions. Dark bars = actual history, green = forecast.`}
      />

      <ContextLabel
        items={[
          { k: "Whose history", v: view.company ? `${view.company.name} — ${view.historical_periods.map((p) => p.period).join(", ")}` : "—" },
          { k: "Compared with", v: `forecast years ${f.years.map((y) => y.period).join(", ")}` },
          { k: "Method", v: f.method.replace(/_/g, " ") },
          { k: "Rule", v: "history informs the drivers, but never overwrites them — you can change any driver" },
        ]}
      />

      <div className="mb-5">
        <HistoryForecast historical={hist} forecast={f} />
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <div className="panel px-4 py-3">
          <div className="micro">How we projected the future years</div>
          <ul className="mt-2 space-y-1 text-[12px] text-muted">
            {f.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        </div>
        <div className="panel px-4 py-3">
          <div className="micro">What actually happened (from reported numbers)</div>
          <ul className="mt-2 space-y-1 text-[12px] text-muted">
            {(view.historical?.facts ?? []).slice(0, 4).map((n, i) => (
              <li key={i} className="text-[#c9ced8]">▸ {n}</li>
            ))}
          </ul>
        </div>
      </div>

      {/* forecast table */}
      <div className="panel overflow-x-auto mb-5">
        <div className="panel-header">
          <span className="micro">Forecast periods</span>
          <span className="text-[10px] text-dim">every cell shows its driver</span>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Period", "Revenue growth", "Revenue", "EBIT margin", "EBIT", "D&A", "CapEx", "ΔNWC", "EBITDA"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {f.years.map((y) => (
              <tr key={y.period} className="row-hover">
                <td className="num px-3 py-1.5 text-[12px] text-accent">{y.period}</td>
                <td className="num px-3 py-1.5 text-[12px] tip" data-tip={tipFor(y.revenue_growth)}>
                  {fmtPct(y.revenue_growth.value)}
                </td>
                <td className="num px-3 py-1.5 text-[12px] text-white tip" data-tip={tipFor(y.revenue)}>
                  {fmtMoney(y.revenue.value)}
                </td>
                <td className="num px-3 py-1.5 text-[12px] tip" data-tip={tipFor(y.ebit_margin)}>
                  {fmtPct(y.ebit_margin.value)}
                </td>
                <td className="num px-3 py-1.5 text-[12px] tip" data-tip={tipFor(y.ebit)}>{fmtMoney(y.ebit.value)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted tip" data-tip={tipFor(y.da)}>{fmtMoney(y.da.value)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted tip" data-tip={tipFor(y.capex)}>{fmtMoney(y.capex.value)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted tip" data-tip={tipFor(y.change_nwc)}>{fmtMoney(y.change_nwc.value)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted tip" data-tip={tipFor(y.ebitda)}>{fmtMoney(y.ebitda.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* historical ratios */}
      <div className="panel overflow-x-auto">
        <div className="panel-header">
          <span className="micro">Historical ratios — facts</span>
          <span className="text-[10px] text-dim">calculated from reported values</span>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Period", "Rev growth", "Gross margin", "EBIT margin", "EBITDA margin", "Effective tax",
                "D&A / rev", "CapEx / rev", "NWC / rev", "FCF margin"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {histRows.map((r) => (
              <tr key={r.period} className="row-hover">
                <td className="num px-3 py-1.5 text-[12px] text-[#dfe3ea]">{r.period}</td>
                {["revenue_growth", "gross_margin", "ebit_margin", "ebitda_margin", "effective_tax_rate",
                  "da_pct", "capex_pct", "nwc_pct", "fcf_margin"].map((k) => (
                  <td key={k} className="num px-3 py-1.5 text-[12px] text-muted">
                    {r.values[k] ? fmtPct(r.values[k].value) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(view.historical?.interpretation?.length ?? 0) > 0 && (
        <div className="mt-4 border border-line bg-ink-900 px-4 py-3">
          <div className="micro">Interpretation — qualitative, clearly separated from facts</div>
          <ul className="mt-2 space-y-1 text-[12px] text-muted">
            {view.historical!.interpretation.map((n, i) => (
              <li key={i}>— {n}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
