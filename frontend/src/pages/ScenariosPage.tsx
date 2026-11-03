/** SCENARIOS — base / bull / bear / custom, instant recompute + comparison. */
import { useEffect, useState } from "react";
import {
  Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { ContextLabel, SectionHeader } from "../components/ui";
import { fmtMoney, fmtPct, fmtSigned } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

const COLORS: Record<string, string> = { base: "#58d6a9", bull: "#4ade80", bear: "#f87171", custom: "#fbbf24" };

export default function ScenariosPage() {
  const { view, applyScenario, busy } = useValuation();
  const [customOpen, setCustomOpen] = useState(false);
  const [customGrowth, setCustomGrowth] = useState<string>("");
  const [customMargin, setCustomMargin] = useState<string>("");

  const sc = view?.scenarios;
  useEffect(() => {
    if (sc?.active === "custom") setCustomOpen(true);
  }, [sc?.active]);

  if (!sc) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No scenarios — run a valuation first.</div>;
  }

  const chart = sc.scenarios.map((s) => ({
    name: s.label.replace(" Case", ""),
    price: s.implied_share_price ?? 0,
    key: s.name,
  }));

  return (
    <div>
      <SectionHeader
        title="Scenario Analysis"
        subtitle="Good year, bad year, or your own case — switching recalculates everything from scratch with the same math used for the base valuation."
      />

      <ContextLabel
        items={[
          { k: "Whose scenarios", v: sc.active ? `currently showing “${sc.active}” case` : "base case" },
          { k: "Compared with", v: "every case shown side by side against the base valuation" },
          { k: "Rule", v: "same formulas, different inputs — no scenario is special-cased" },
        ]}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 mb-5">
        {sc.scenarios.map((s) => {
          const active = sc.active === s.name;
          return (
            <button
              key={s.name}
              disabled={busy || !s.valid}
              onClick={() => void applyScenario(s.name)}
              className={`panel px-4 py-3.5 text-left transition-colors ${
                active ? "border-accent-dim bg-accent/5" : "hover:border-ink-600"
              } ${!s.valid ? "opacity-50" : ""}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-[13px] tracking-wide" style={{ color: COLORS[s.name] ?? "#dfe3ea" }}>
                  {s.label}
                </span>
                {active && <span className="text-[9px] uppercase tracking-widest text-accent">active</span>}
              </div>
              <div className="num mt-2 text-[20px] text-white">
                {s.implied_share_price != null ? fmtMoney(s.implied_share_price, "$", 2) : "n/a"}
              </div>
              <div className="mt-1 space-y-0.5 text-[11px] text-dim">
                <div>WACC {fmtPct(s.wacc)} · g {fmtPct(s.terminal_growth)}</div>
                <div>EV {fmtMoney(s.enterprise_value)} · Equity {fmtMoney(s.equity_value)}</div>
                <div className={s.valid ? "" : "text-down"}>
                  {s.valid
                    ? s.upside_downside != null
                      ? `vs market ${fmtSigned(s.upside_downside)}`
                      : "no market price"
                    : s.issue}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-5">
        <div className="panel px-3 py-3">
          <div className="micro px-1 pb-2">Implied share price by scenario</div>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#171a21" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "#5c6371", fontSize: 11 }} axisLine={{ stroke: "#1e222c" }} tickLine={false} />
              <YAxis tick={{ fill: "#5c6371", fontSize: 10 }} axisLine={false} tickLine={false}
                     tickFormatter={(v: number) => `$${v.toFixed(0)}`} width={44} />
              <Tooltip
                contentStyle={{ background: "#0d0f13", border: "1px solid #1e222c", borderRadius: 0, fontSize: 12 }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, "implied price"]}
              />
              <ReferenceLine y={view?.summary?.current_share_price ?? 0} stroke="#8b93a7" strokeDasharray="3 3" />
              <Bar dataKey="price" barSize={42}>
                {chart.map((c) => <Cell key={c.key} fill={COLORS[c.key] ?? "#58d6a9"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="px-1 pt-1 text-[10.5px] text-dim">
            Dashed line = current share price (when available).
          </p>
        </div>

        <div className="panel overflow-x-auto">
          <div className="panel-header"><span className="micro">Scenario comparison</span></div>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-line">
                {["Scenario", "Δ overrides", "WACC", "g", "EV", "Equity", "Price"].map((h) => (
                  <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {sc.scenarios.map((s) => (
                <tr key={s.name} className={`row-hover ${sc.active === s.name ? "bg-accent/5" : ""}`}>
                  <td className="px-3 py-1.5 text-[12.5px]" style={{ color: COLORS[s.name] }}>{s.label}</td>
                  <td className="px-3 py-1.5 text-[11px] text-dim max-w-[180px] truncate" title={JSON.stringify(s.overrides)}>
                    {Object.entries(s.overrides).slice(0, 3).map(([k, v]) => `${k} ${v >= 0 ? "+" : ""}${v.toFixed(3)}`).join(", ") || "—"}
                  </td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtPct(s.wacc)}</td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtPct(s.terminal_growth)}</td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(s.enterprise_value)}</td>
                  <td className="num px-3 py-1.5 text-[12px]">{fmtMoney(s.equity_value)}</td>
                  <td className="num px-3 py-1.5 text-[12px] text-white">{fmtMoney(s.implied_share_price, "$", 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="micro">Custom case</div>
          <button className="btn-ghost !py-1" onClick={() => setCustomOpen((o) => !o)}>
            {customOpen ? "close" : "define custom overrides"}
          </button>
        </div>
        {customOpen && (
          <div className="mt-3 grid gap-3 sm:grid-cols-[200px_200px_auto] sm:items-end">
            <label className="block">
              <span className="micro">Revenue growth (%, applied over base)</span>
              <input className="input mt-1" placeholder="6.5" value={customGrowth}
                     onChange={(e) => setCustomGrowth(e.target.value)} />
            </label>
            <label className="block">
              <span className="micro">EBIT margin (%)</span>
              <input className="input mt-1" placeholder="20" value={customMargin}
                     onChange={(e) => setCustomMargin(e.target.value)} />
            </label>
            <button
              className="btn-primary"
              disabled={busy}
              onClick={() => {
                const overrides: Record<string, number> = {};
                if (customGrowth.trim() !== "") overrides.revenue_growth = Number(customGrowth) / 100;
                if (customMargin.trim() !== "") overrides.ebit_margin = Number(customMargin) / 100;
                void applyScenario("custom", overrides);
              }}
            >
              Apply custom case
            </button>
          </div>
        )}
        <p className="mt-2 text-[11.5px] text-dim">
          Custom overrides are absolute values (not deltas). All other drivers keep their base settings.
        </p>
      </div>
    </div>
  );
}
