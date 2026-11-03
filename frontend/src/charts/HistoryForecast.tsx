/** Historical vs forecast chart — periods visually distinct. */
import {
  Bar, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, Cell,
} from "recharts";
import type { ForecastResult, PeriodData } from "../types/api";

export default function HistoryForecast({
  historical, forecast,
}: { historical: PeriodData[]; forecast?: ForecastResult | null }) {
  const hist = historical.map((p) => ({
    name: p.period,
    revenue: p.metrics["revenue"]?.value ?? null,
    ebit: p.metrics["ebit"]?.value ?? null,
    kind: "hist" as const,
  }));
  const f = (forecast?.years ?? []).map((y) => ({
    name: y.period,
    revenue: y.revenue.value,
    ebit: y.ebit.value,
    kind: "fcst" as const,
  }));
  const data = [...hist, ...f];
  if (!data.length) return null;

  return (
    <div className="panel px-3 py-3">
      <div className="flex items-center gap-4 px-1 pb-2">
        <span className="micro">Revenue & EBIT — actual vs forecast</span>
        <span className="flex items-center gap-1.5 text-[10px] text-dim">
          <span className="h-2 w-3 bg-[#3b4454]" /> historical
        </span>
        <span className="flex items-center gap-1.5 text-[10px] text-dim">
          <span className="h-2 w-3 bg-accent/70" /> forecast
        </span>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="#171a21" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "#5c6371", fontSize: 10 }} axisLine={{ stroke: "#1e222c" }} tickLine={false} />
          <YAxis tick={{ fill: "#5c6371", fontSize: 10 }} axisLine={false} tickLine={false}
                 tickFormatter={(v: number) => `${(v / 1e9).toFixed(1)}B`} width={46} />
          <Tooltip
            contentStyle={{ background: "#0d0f13", border: "1px solid #1e222c", borderRadius: 0, fontSize: 12 }}
            labelStyle={{ color: "#878e9c" }}
            formatter={(v: number, name: string) => [
              `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
              name,
            ]}
          />
          <Bar dataKey="revenue" barSize={22}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.kind === "hist" ? "#3b4454" : "rgba(88,214,169,0.65)"} />
            ))}
          </Bar>
          <Line dataKey="ebit" stroke="#9fb3c8" strokeWidth={1.4} dot={{ r: 2 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
