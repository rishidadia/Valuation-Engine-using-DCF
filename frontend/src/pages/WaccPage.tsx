/** WACC — interactive builder: change inputs, see WACC update instantly (client mirror). */
import { useMemo, useState } from "react";
import { ContextLabel, FormulaBox, SectionHeader, SourceBadge, StatusText } from "../components/ui";
import { fmtNum, fmtPct, tipFor } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function WaccPage() {
  const { view, applyAssumptions, busy } = useValuation();
  const wacc = view?.wacc;
  const [rf, setRf] = useState<number | null>(null);
  const [beta, setBeta] = useState<number | null>(null);
  const [mrp, setMrp] = useState<number | null>(null);
  const [rd, setRd] = useState<number | null>(null);
  const [tax, setTax] = useState<number | null>(null);
  const [wd, setWd] = useState<number | null>(null);

  const live = useMemo(() => {
    const e_rf = rf ?? wacc?.risk_free_rate.value ?? 0;
    const e_beta = beta ?? wacc?.beta.value ?? 1;
    const e_mrp = mrp ?? wacc?.market_risk_premium.value ?? 0.05;
    const e_rd = rd ?? wacc?.cost_of_debt.value ?? 0.05;
    const e_tax = tax ?? wacc?.tax_rate.value ?? 0.21;
    const e_wd = wd ?? wacc?.debt_weight.value ?? 0;
    const re = e_rf + e_beta * e_mrp;
    const we = 1 - e_wd;
    const w = we * re + e_wd * e_rd * (1 - e_tax);
    return { rf: e_rf, beta: e_beta, mrp: e_mrp, rd: e_rd, tax: e_tax, wd: e_wd, we, re, w,
             changed: rf != null || beta != null || mrp != null || rd != null || tax != null || wd != null };
  }, [rf, beta, mrp, rd, tax, wd, wacc]);

  if (!view || !wacc) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No WACC yet — run a valuation first.</div>;
  }

  const dirty = live.changed;
  const serverWacc = wacc.wacc.value ?? 0;

  const apply = async () => {
    const overrides: Record<string, number> = {};
    if (rf != null) overrides.risk_free_rate = rf / 100;
    if (beta != null) overrides.beta = beta;
    if (mrp != null) overrides.market_risk_premium = mrp / 100;
    if (rd != null) overrides.cost_of_debt = rd / 100;
    if (tax != null) overrides.tax_rate = tax / 100;
    if (wd != null) {
      overrides.debt_weight = wd / 100;
      overrides.equity_weight = 1 - wd / 100;
    }
    await applyAssumptions(overrides, [], {
      ...view.options,
      cost_of_equity_method: "capm",
      capital_structure_method: wd != null ? "manual" : (view.options?.capital_structure_method ?? "current"),
      cost_of_debt_method: rd != null ? "manual" : (view.options?.cost_of_debt_method ?? "interest_bearing"),
      tax_rate_method: tax != null ? "manual" : (view.options?.tax_rate_method ?? "historical_effective"),
    });
    setRf(null); setBeta(null); setMrp(null); setRd(null); setTax(null); setWd(null);
  };

  const inputs: [string, number | null, (v: number) => void, number, number, number, string][] = [
    ["Risk-Free Rate", rf, (v) => setRf(v), live.rf * 100, -2, 15, "%"],
    ["Beta", beta, (v) => setBeta(v), live.beta, -1, 4, ""],
    ["Market Risk Prem.", mrp, (v) => setMrp(v), live.mrp * 100, 0, 15, "%"],
    ["Cost of Debt", rd, (v) => setRd(v), live.rd * 100, 0, 30, "%"],
    ["Tax Rate", tax, (v) => setTax(v), live.tax * 100, 0, 50, "%"],
    ["Debt Weight", wd, (v) => setWd(v), live.wd * 100, 0, 100, "%"],
  ];

  const drift = Math.abs(live.w - serverWacc);

  return (
    <div>
      <SectionHeader
        title="WACC Builder"
        subtitle="The discount rate — the return both debt and equity holders require. Move any slider to see its effect instantly; press Apply to make it official."
        right={
          <button className="btn-primary" disabled={!dirty || busy} onClick={apply}>
            {busy ? "Recomputing…" : "Apply as overrides"}
          </button>
        }
      />

      <ContextLabel
        items={[
          { k: "Whose cost of capital", v: view.company ? `${view.company.name}${view.company.ticker ? ` (${view.company.ticker})` : ""}` : "this company" },
          { k: "Compared with", v: "your live sliders ↔ the saved official values (shown below each slider)" },
          { k: "Used for", v: "discounting future cash flows on the DCF page" },
          { k: "Every input", v: "labelled with its source in the provenance table" },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="panel px-4 py-4">
          <div className="micro mb-3">Inputs</div>
          <div className="space-y-4">
            {inputs.map(([label, val, set, base, lo, hi, suffix]) => (
              <div key={label}>
                <div className="flex items-baseline justify-between">
                  <span className="text-[12px] text-muted">{label}</span>
                  <span className="num text-[12px] text-[#dfe3ea]">
                    {suffix === "%" ? `${(val ?? base).toFixed(2)}%` : (val ?? base).toFixed(2)}
                  </span>
                </div>
                <input
                  type="range"
                  className="mt-1 w-full accent-[#58d6a9]"
                  min={lo}
                  max={hi}
                  step={label === "Beta" ? 0.01 : 0.05}
                  value={val ?? base}
                  onChange={(e) => set(Number(e.target.value))}
                />
                <div className="flex justify-between text-[10px] text-dim">
                  <span>server: {suffix === "%" ? `${(base).toFixed(2)}%` : base.toFixed(2)}</span>
                  {val != null && <span className="text-orange-300">unsaved override</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
        <div className="panel px-4 py-4">
          <div className="micro mb-3">Live computation — what the sliders add up to</div>
            <FormulaBox
              text={`Re = Rf + β × MRP = ${fmtPct(live.rf)} + (${fmtNum(live.beta, 2)} × ${fmtPct(live.mrp)})`}
              result={`= ${fmtPct(live.re)}`}
            />
            <div className="h-3" />
            <FormulaBox
              text={`WACC = (E/(D+E)) × Re + (D/(D+E)) × Rd × (1 − T)\n     = (${fmtPct(live.we)} × ${fmtPct(live.re)}) + (${fmtPct(live.wd)} × ${fmtPct(live.rd)} × (1 − ${fmtPct(live.tax)}))`}
              result={`= ${fmtPct(live.w)}${dirty ? `   (server: ${fmtPct(serverWacc)}, Δ ${fmtPct(drift)})` : ""}`}
            />
          </div>

          <div className="panel px-4 py-4">
            <div className="micro mb-1">Where each input comes from</div>
            <p className="mb-2 text-[11.5px] text-dim">
              Hover any number to see its full provenance. Badges show whether it was
              retrieved, calculated or typed in by you.
            </p>
            <table className="w-full text-left">
              <tbody className="divide-y divide-line">
                {[
                  ["Market value of equity", wacc.market_value_equity],
                  ["Market value of debt", wacc.market_value_debt],
                  ["Equity weight", wacc.equity_weight],
                  ["Debt weight", wacc.debt_weight],
                  ["Risk-free rate", wacc.risk_free_rate],
                  ["Beta", wacc.beta],
                  ["Market risk premium", wacc.market_risk_premium],
                  ["Cost of equity", wacc.cost_of_equity],
                  ["Cost of debt", wacc.cost_of_debt],
                  ["After-tax cost of debt", wacc.after_tax_cost_of_debt],
                  ["Tax rate", wacc.tax_rate],
                  ["WACC", wacc.wacc],
                ].map(([label, sv]) => {
                  const s = sv as typeof wacc.wacc;
                  const isPct = s.unit === "percent";
                  return (
                    <tr key={String(label)} className="row-hover">
                      <td className="py-1.5 text-[12px] text-[#dfe3ea]">{String(label)}</td>
                      <td className="num py-1.5 text-[12px] text-right tip" data-tip={tipFor(s)}>
                        {isPct ? fmtPct(s.value) : s.unit === "currency" || s.unit === undefined
                          ? (s.currency && s.value ? `${s.currency} ` : "") +
                            (s.value != null ? s.value.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—")
                          : fmtNum(s.value, 3)}
                      </td>
                      <td className="py-1.5 pl-3"><SourceBadge type={s.source_type} /></td>
                      <td className="py-1.5"><StatusText status={s.status} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* sensitivity to WACC inputs — computed client-side from CAPM identity */}
      <div className="mt-5 panel px-4 py-4">
        <div className="micro mb-3">How WACC moves with each input (identity-based, all else fixed)</div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Beta ±0.25", low: we_re(live, live.beta - 0.25), high: we_re(live, live.beta + 0.25) },
            { label: "Risk-free ±1.0pp", low: waccWithRf(live, live.rf - 1), high: waccWithRf(live, live.rf + 1) },
            { label: "MRP ±1.0pp", low: waccWithMrp(live, live.mrp - 1), high: waccWithMrp(live, live.mrp + 1) },
            { label: "Debt weight ±10pp", low: waccWithWd(live, Math.max(0, live.wd - 0.1)), high: waccWithWd(live, Math.min(1, live.wd + 0.1)) },
          ].map((r) => (
            <div key={r.label} className="border border-line px-3 py-2.5">
              <div className="text-[11px] text-muted">{r.label}</div>
              <div className="num mt-1 text-[13px]">
                <span className="text-down">{fmtPct(r.low)}</span>
                <span className="text-dim"> → </span>
                <span className="text-up">{fmtPct(r.high)}</span>
              </div>
              <div className="mt-1 text-[10px] text-dim">base {fmtPct(live.w)}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 h-1.5 w-full bg-ink-850">
          <div className="h-full bg-accent/60" style={{ width: `${Math.min(100, (live.w / 0.25) * 100)}%` }} />
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-dim"><span>0%</span><span>25% WACC</span></div>
      </div>

      {wacc.warnings.length > 0 && (
        <div className="mt-4 border border-warn/30 bg-warn/5 px-4 py-3">
          <div className="micro text-warn">WACC warnings</div>
          <ul className="mt-1 space-y-1 text-[12px] text-warn/90">
            {wacc.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
          </ul>
        </div>
      )}

      <div className="mt-4">
        <FormulaBox text={wacc.capm_formula} />
      </div>
    </div>
  );
}

type Live = { rf: number; beta: number; mrp: number; rd: number; tax: number; wd: number; we: number; re: number; w: number; changed: boolean };

// live.* fields are decimals (0.05 == 5%); slider args arrive in percent space.
function we_re(l: Live, beta: number) {
  const re = l.rf + beta * l.mrp;
  return l.we * re + l.wd * l.rd * (1 - l.tax);
}
function waccWithRf(l: Live, rfPct: number) {
  const re = rfPct / 100 + l.beta * l.mrp;
  return l.we * re + l.wd * l.rd * (1 - l.tax);
}
function waccWithMrp(l: Live, mrpPct: number) {
  const re = l.rf + l.beta * (mrpPct / 100);
  return l.we * re + l.wd * l.rd * (1 - l.tax);
}
function waccWithWd(l: Live, wd: number) {
  const re = l.rf + l.beta * l.mrp;
  return (1 - wd) * re + wd * l.rd * (1 - l.tax);
}
