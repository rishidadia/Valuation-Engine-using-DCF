/** Tornado chart: valuation swing per input (conditional ranges). */
import {
  Bar, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, BarChart,
} from "recharts";
import type { TornadoItem } from "../types/api";

export default function TornadoChart({ items }: { items: TornadoItem[] }) {
  const data = items
    .filter((i) => i.low_result != null || i.high_result != null)
    .map((i) => ({
      name: i.label,
      base: i.base_result ?? 0,
      low: i.low_result ?? i.base_result ?? 0,
      high: i.high_result ?? i.base_result ?? 0,
      swing: i.swing ?? 0,
    }));

  if (!data.length) return null;

  return (
    <div className="panel px-3 py-3">
      <div className="micro px-1 pb-2">Valuation swing by input (one-at-a-time, all else fixed)</div>
      <ResponsiveContainer width="100%" height={Math.max(220, data.length * 34)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="#171a21" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#5c6371", fontSize: 10 }} axisLine={false} tickLine={false}
                 tickFormatter={(v: number) => `$${(v / 1).toFixed(0)}`} />
          <YAxis type="category" dataKey="name" tick={{ fill: "#878e9c", fontSize: 10 }} axisLine={false}
                 tickLine={false} width={150} />
          <Tooltip
            contentStyle={{ background: "#0d0f13", border: "1px solid #1e222c", borderRadius: 0, fontSize: 12 }}
            formatter={(v: number, name: string) => [
              `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`,
              name,
            ]}
          />
          <ReferenceLine x={data[0]?.base ?? 0} stroke="#58d6a9" strokeDasharray="3 3" />
          <Bar dataKey="low" fill="#f87171" barSize={12} />
          <Bar dataKey="high" fill="#58d6a9" barSize={12} />
        </BarChart>
      </ResponsiveContainer>
      <p className="px-1 pt-1 text-[10.5px] text-dim">
        Red = input at low end of range, green = high end; dashed line = base valuation.
        These are conditional ranges, not predictions.
      </p>
    </div>
  );
}
