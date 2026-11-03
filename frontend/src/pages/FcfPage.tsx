/** FCF — expandable year rows: every component of UFCF shown. */
import { Fragment, useState } from "react";
import FcfChart from "../charts/FcfChart";
import { ContextLabel, SectionHeader } from "../components/ui";
import { fmtMoney, fmtPct, fmtValue, tipFor } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function FcfPage() {
  const { view } = useValuation();
  const [open, setOpen] = useState<string | null>(null);
  const fcf = view?.fcf;

  if (!fcf) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No FCF schedule — run a valuation first.</div>;
  }

  return (
    <div>
      <SectionHeader
        title="Free Cash Flow"
        subtitle="The cash the business actually generates after costs, tax and reinvestment — the numbers being discounted. Expand any year to see the arithmetic."
        right={
          fcf.fcf_cagr != null ? (
            <span className="num text-[13px] text-accent">FCF CAGR {fmtPct(fcf.fcf_cagr, 1)}</span>
          ) : undefined
        }
      />

      <ContextLabel
        items={[
          { k: "Whose cash flows", v: view?.company ? `${view.company.name} — forecast years ${fcf.years.map((y) => y.period).join(", ")}` : "—" },
          { k: "Formula", v: "EBIT after tax + depreciation − capital spending − working-capital change" },
          { k: "Compared with", v: "each year's FCF is discounted back to today at the WACC" },
        ]}
      />

      <div className="mb-5">
        <FcfChart schedule={fcf} />
      </div>

      <div className="panel overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["", "Year", "Revenue", "EBIT", "Tax rate", "Tax", "NOPAT", "D&A", "CapEx", "ΔNWC",
                "FCF", "Discount factor", "PV(FCF)"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {fcf.years.map((y) => {
              const isOpen = open === y.period;
              return (
                <Fragment key={y.period}>
                  <tr
                    className={`row-hover cursor-pointer ${isOpen ? "bg-ink-850" : ""}`}
                    onClick={() => setOpen(isOpen ? null : y.period)}
                  >
                    <td className="px-3 py-1.5 text-[11px] text-dim">{isOpen ? "▾" : "▸"}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-accent">{y.period}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-muted tip" data-tip={tipFor(y.revenue)}>{fmtMoney(y.revenue.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] tip" data-tip={tipFor(y.ebit)}>{fmtMoney(y.ebit.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtPct(y.tax_rate.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-down/90">{fmtMoney(-Math.abs(y.tax_expense.value ?? 0))}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(y.nopat.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-muted">{fmtMoney(y.da.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-down/90">{fmtMoney(y.capex.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-down/90">{fmtMoney(y.change_nwc.value)}</td>
                    <td className="num px-3 py-1.5 text-[13px] text-white font-medium">{fmtMoney(y.fcf.value)}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-muted">{y.discount_factor?.toFixed(4) ?? "—"}</td>
                    <td className="num px-3 py-1.5 text-[12px] text-accent">{fmtMoney(y.pv_fcf)}</td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={13} className="bg-ink-850 px-6 py-4">
                        <div className="grid gap-4 lg:grid-cols-2">
                          <div>
                            <div className="micro mb-2">Calculation walk — {y.period}</div>
                            <ol className="space-y-1.5 text-[12.5px]">
                              <Step n="1" text={`EBIT margin applied: ${fmtPct(y.ebit.value && y.revenue.value ? y.ebit.value / y.revenue.value : null)} of revenue`} />
                              <Step n="2" text={`Tax on EBIT = ${fmtMoney(y.ebit.value)} × ${fmtPct(y.tax_rate.value)} = ${fmtMoney(y.tax_expense.value)}`} />
                              <Step n="3" text={`NOPAT = ${fmtMoney(y.ebit.value)} − ${fmtMoney(y.tax_expense.value)} = ${fmtMoney(y.nopat.value)}`} />
                              <Step n="4" text={`+ D&A  ${fmtMoney(y.da.value)}`} />
                              <Step n="5" text={`− CapEx  ${fmtMoney(y.capex.value)}`} />
                              <Step n="6" text={`− ΔNWC  ${fmtMoney(y.change_nwc.value)}`} />
                              <Step n="7" text={`= FCF  ${fmtMoney(y.fcf.value)}`} strong />
                              <Step n="8" text={`× DF ${y.discount_factor?.toFixed(6) ?? "—"} = PV ${fmtMoney(y.pv_fcf)}`} strong />
                            </ol>
                          </div>
                          <div>
                            <div className="micro mb-2">Exact formula (backend)</div>
                            <div className="num border border-line bg-ink-900 px-3 py-2 text-[12px] leading-relaxed text-[#cfd4dd]">
                              {y.formula}
                            </div>
                            <div className="micro mt-3 mb-1">Component notes</div>
                            <ul className="space-y-1 text-[11.5px] text-muted">
                              <li>EBIT: {y.ebit.note}</li>
                              <li>D&A: {y.da.note}</li>
                              <li>CapEx: {y.capex.note} (positive = outflow)</li>
                              <li>ΔNWC: {y.change_nwc.note}</li>
                              <li>FCF margin: {fmtValue(fcf.margins[y.year_index - 1], "percent")}</li>
                            </ul>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 border border-line bg-ink-900 px-4 py-3">
        <div className="micro">Notes</div>
        <ul className="mt-1.5 space-y-1 text-[12px] text-muted">
          {fcf.notes.map((n, i) => <li key={i}>• {n}</li>)}
        </ul>
      </div>
    </div>
  );
}

function Step({ n, text, strong }: { n: string; text: string; strong?: boolean }) {
  return (
    <li className={`flex items-baseline gap-2 ${strong ? "text-white" : "text-muted"}`}>
      <span className="num w-4 text-center text-[10px] text-dim">{n}</span>
      <span className="num">{text}</span>
    </li>
  );
}
