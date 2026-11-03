/** DCF — discounting, both terminal methods, EV→equity→price bridge. */
import { ContextLabel, SectionHeader, FormulaBox, StatTile, VerdictStrip } from "../components/ui";
import { fmtMoney, fmtPct, fmtSigned, tipFor } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function DcfPage() {
  const { view } = useValuation();
  const dcf = view?.dcf;

  if (!dcf) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No DCF yet — run a valuation first.</div>;
  }

  return (
    <div>
      <SectionHeader
        title="DCF Valuation"
        subtitle={`What the business is worth: the ${dcf.forecast_years}-year cash forecast, translated into today's money at a ${fmtPct(dcf.discount_rate)} discount rate.`}
      />

      <ContextLabel
        items={[
          { k: "Whose valuation", v: view?.company ? `${view.company.name}${view.company.ticker ? ` (${view.company.ticker})` : ""}` : "this company" },
          { k: "Compared with", v: dcf.current_share_price != null ? `our estimate ↔ today's real market price (${fmtMoney(dcf.current_share_price, "$", 2)})` : "no market price (private company)" },
          { k: "Method", v: dcf.selected_method.replace(/_/g, " ") + " terminal value" },
          { k: "Based on", v: "the forecast, WACC and assumptions you reviewed" },
        ]}
      />

      <VerdictStrip
        implied={dcf.implied_share_price}
        market={dcf.current_share_price}
        upside={dcf.upside_downside}
        basis={`Discount rate ${fmtPct(dcf.discount_rate)} · terminal growth ${fmtPct(dcf.terminal_growth ?? null)} · every input is listed on the WACC and Assumptions pages.`}
      />

      {dcf.issue && (
        <div className="mb-4 border border-down/40 bg-down/5 px-4 py-3">
          <div className="micro text-down">Terminal value blocked</div>
          <p className="mt-1 text-[12.5px] text-[#f8d4d4]">{dcf.issue}</p>
        </div>
      )}

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 stagger">
        <StatTile label="What the whole business is worth (EV)" value={fmtMoney(dcf.enterprise_value)} sub="value of all operations, before cash & debt" />
        <StatTile label="What the shares are worth (equity)" value={fmtMoney(dcf.equity_value)} sub="EV + cash − debt" />
        <StatTile
          label="Our value per share"
          value={dcf.implied_share_price != null ? fmtMoney(dcf.implied_share_price, "$", 2) : "unavailable"}
          sub={dcf.shares_outstanding ? `equity ÷ ${fmtMoney(dcf.shares_outstanding)} shares` : "shares outstanding missing"}
          tone={dcf.implied_share_price != null ? "default" : "down"}
        />
        <StatTile
          label="vs market price"
          value={fmtSigned(dcf.upside_downside)}
          sub={dcf.current_share_price ? `estimate compared to ${fmtMoney(dcf.current_share_price, "$", 2)} market` : "private company — no market price"}
          tone={(dcf.upside_downside ?? 0) >= 0 ? "up" : "down"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* terminal methods side by side */}
        <div className="panel px-4 py-4">
          <div className="micro mb-1">What happens after the 5-year forecast?</div>
          <p className="mb-3 text-[11.5px] text-dim">
            Both common ways of estimating the far future are always shown side by side.
            The selected one drives the headline number.
          </p>
          <div className="space-y-4">
            {dcf.terminal_methods.map((m) => (
              <div key={m.method} className={`border px-3 py-3 ${m.valid ? "border-line" : "border-down/40 bg-down/[0.04]"}`}>
                <div className="flex items-center justify-between">
                  <span className="text-[12.5px] text-[#dfe3ea]">{m.label}</span>
                  <span className={`text-[10px] uppercase tracking-widest ${m.valid ? "text-up" : "text-down"}`}>
                    {m.valid ? (m.method === dcf.selected_method ? "selected" : "valid") : "blocked"}
                  </span>
                </div>
                {m.valid ? (
                  <>
                    <div className="num mt-2 text-[11.5px] leading-relaxed text-muted break-words">{m.formula}</div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-[12px]">
                      <div>
                        <span className="text-dim">Terminal value </span>
                        <span className="num text-white">{fmtMoney(m.terminal_value)}</span>
                      </div>
                      <div>
                        <span className="text-dim">PV(TV) </span>
                        <span className="num text-white">{fmtMoney(m.pv_terminal_value)}</span>
                      </div>
                      <div>
                        <span className="text-dim">EV </span>
                        <span className="num text-white">{fmtMoney(m.ev)}</span>
                      </div>
                      <div>
                        <span className="text-dim">Price </span>
                        <span className="num text-accent">{m.implied_share_price != null ? fmtMoney(m.implied_share_price, "$", 2) : "—"}</span>
                      </div>
                    </div>
                    <div className="mt-1.5 text-[10.5px] text-dim">
                      TV share of EV: {m.pv_terminal_value && m.ev ? fmtPct(m.pv_terminal_value / m.ev, 0) : "—"}
                    </div>
                  </>
                ) : (
                  <div className="num mt-2 text-[11.5px] text-[#f3c9c9]">{m.issue}</div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* equity bridge */}
        <div className="panel px-4 py-4">
          <div className="micro mb-1">From business value to value per share</div>
          <p className="mb-2 text-[11.5px] text-dim">
            Add the cash, subtract the debt, divide by the number of shares.
          </p>
          <table className="w-full">
            <tbody className="divide-y divide-line">
              {dcf.bridge.map((b, i) => {
                const isTotal = ["Enterprise Value", "Equity Value", "Implied Share Price"].includes(b.label);
                const isDiv = b.label.startsWith("÷");
                return (
                  <tr key={i} className={isTotal ? "bg-ink-850" : ""}>
                    <td className={`py-2 text-[12.5px] ${isTotal ? "text-white" : "text-muted"}`}>{b.label}</td>
                    <td className="py-2 text-right">
                      <span className={`num ${isTotal ? "text-[14px] text-white" : isDiv ? "text-[12px] text-dim" : "text-[12.5px] text-[#dfe3ea]"}`}>
                        {isDiv ? fmtMoney(b.value) : b.label.includes("price") ? fmtMoney(b.value, "$", 2) : fmtMoney(b.value)}
                      </span>
                    </td>
                    <td className="py-2 pl-3 text-right text-[10.5px] text-dim max-w-[220px] truncate" title={b.detail}>{b.detail}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* PV schedule */}
      <div className="mt-5 panel overflow-x-auto">
        <div className="panel-header">
          <span className="micro">PV of forecast cash flows</span>
          <span className="num text-[11px] text-accent">Σ PV = {fmtMoney(dcf.pv_forecast_fcf)}</span>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Year", "FCF", "Discount factor", "PV(FCF)", "Share of total"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {dcf.pv_rows.map((r) => (
              <tr key={r.period} className="row-hover">
                <td className="num px-3 py-1.5 text-[12px] text-accent">{r.period}</td>
                <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(r.fcf)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-muted">{r.discount_factor.toFixed(4)}</td>
                <td className="num px-3 py-1.5 text-[12px] text-white">{fmtMoney(r.pv)}</td>
                <td className="px-3 py-1.5">
                  <div className="h-1.5 w-32 bg-ink-850">
                    <div className="h-full bg-accent/50"
                         style={{ width: `${Math.max(1, ((r.pv / (dcf.pv_forecast_fcf || 1)) * 100)).toFixed(1)}%` }} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dcf.warnings.length > 0 && (
        <div className="mt-4 border border-warn/30 bg-warn/5 px-4 py-3">
          <div className="micro text-warn">DCF warnings</div>
          <ul className="mt-1 space-y-1 text-[12px] text-warn/90">
            {dcf.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
          </ul>
        </div>
      )}

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <FormulaBox
          text={`PV(FCF) = Σ FCF_t / (1 + WACC)^t   over ${dcf.forecast_years} years @ ${fmtPct(dcf.discount_rate)}`}
          result={`= ${fmtMoney(dcf.pv_forecast_fcf)}`}
        />
        <div className="border border-line bg-ink-850 px-3 py-2.5 text-[11.5px] text-muted leading-relaxed">
          Perpetuity: TV = FCFₙ × (1 + g) / (WACC − g) — blocked automatically when WACC ≤ g.
          Exit multiple: TV = terminal EBITDA × exit multiple. Both are shown whenever sufficient data exists;
          the selected method drives the headline number.
        </div>
      </div>
    </div>
  );
}
