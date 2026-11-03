/** SENSITIVITY — two-way heatmaps + single-factor swings (ranges, not predictions). */
import TornadoChart from "../charts/TornadoChart";
import Heatmap from "../components/Heatmap";
import { ContextLabel, SectionHeader } from "../components/ui";
import { fmtMoney } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function SensitivityPage() {
  const { view } = useValuation();
  const s = view?.sensitivity;

  if (!s) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No sensitivity results — run a valuation first.</div>;
  }

  const flat = s.tables.flatMap((t) => t.matrix.flat()).filter((v): v is number => v != null);

  return (
    <div>
      <SectionHeader
        title="Sensitivity Analysis"
        subtitle="How much the answer moves when each assumption moves — every cell is a full re-run of the valuation, not an approximation."
        right={
          <span className="num text-[13px] text-muted">
            base {fmtMoney(s.base_implied_price, "$", 2)}
            {flat.length > 0 && (
              <span className="text-dim">
                {" "}· range {fmtMoney(Math.min(...flat), "$", 2)} – {fmtMoney(Math.max(...flat), "$", 2)}
              </span>
            )}
          </span>
        }
      />

      <ContextLabel
        items={[
          { k: "Whose value", v: view?.company ? `${view.company.name}${view.company.ticker ? ` (${view.company.ticker})` : ""}` : "—" },
          { k: "Compared with", v: `every cell ↔ the base case of ${fmtMoney(s.base_implied_price, "$", 2)} per share` },
          { k: "Read as", v: "conditional ranges — what would happen IF an input changed, not predictions" },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-2 mb-5 stagger">
        {s.tables.map((t) => <Heatmap key={t.key} table={t} />)}
      </div>

      <div className="mb-5">
        <TornadoChart items={s.tornado} />
      </div>

      <div className="panel overflow-x-auto">
        <div className="panel-header">
          <span className="micro">Input swings — exact values</span>
          <span className="text-[10px] text-dim">one-at-a-time</span>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Input", "Range", "Valuation at low", "Valuation at high", "Swing", "Base"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {s.tornado.map((t) => (
              <tr key={t.input_key} className="row-hover">
                <td className="px-3 py-1.5 text-[12.5px] text-[#dfe3ea]">{t.label}</td>
                <td className="num px-3 py-1.5 text-[11.5px] text-muted">
                  {t.low.toFixed(3)} → {t.high.toFixed(3)}
                </td>
                <td className="num px-3 py-1.5 text-[12px] text-down">{fmtMoney(t.low_result, "$", 2)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-up">{fmtMoney(t.high_result, "$", 2)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-white">{fmtMoney(t.swing, "$", 2)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(t.base_result, "$", 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="mt-4 space-y-1 text-[11.5px] text-dim">
        {s.notes.map((n, i) => <li key={i}>• {n}</li>)}
      </ul>
    </div>
  );
}
