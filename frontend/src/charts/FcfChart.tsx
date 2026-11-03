/** FCF build chart: NOPAT + D&A − CapEx − ΔNWC per forecast year. */
import {
  Bar, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import type { FcfSchedule } from "../types/api";

const COLORS = {
  nopat: "#58d6a9",
  da: "#60a5fa",
  capex: "#f87171",
  nwc: "#fbbf24",
  fcf: "#e7e9ee",
};

export default function FcfChart({ schedule }: { schedule: FcfSchedule }) {
  const data = schedule.years.map((y) => ({
    name: y.period,
    NOPAT: y.nopat.value,
    "D&A": y.da.value,
    CapEx: -(y.capex.value ?? 0),
    "ΔNWC": -(y.change_nwc.value ?? 0),
    FCF: y.fcf.value,
    PV: y.pv_fcf ?? null,
  }));

  return (
    <div className="panel px-3 py-3">
      <div className="micro px-1 pb-2">FCF components per year (outflows shown negative)</div>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="#171a21" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "#5c6371", fontSize: 10 }} axisLine={{ stroke: "#1e222c" }} tickLine={false} />
          <YAxis tick={{ fill: "#5c6371", fontSize: 10 }} axisLine={false} tickLine={false}
                 tickFormatter={(v: number) => `${(v / 1e6).toFixed(0)}M`} width={46} />
          <Tooltip
            contentStyle={{ background: "#0d0f13", border: "1px solid #1e222c", borderRadius: 0, fontSize: 12 }}
            labelStyle={{ color: "#878e9c" }}
            formatter={(v: number, name: string) => [
              `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: "#878e9c" }} />
          <Bar dataKey="NOPAT" stackId="a" fill={COLORS.nopat} barSize={26} />
          <Bar dataKey="D&A" stackId="a" fill={COLORS.da} />
          <Bar dataKey="CapEx" stackId="a" fill={COLORS.capex} />
          <Bar dataKey="ΔNWC" stackId="a" fill={COLORS.nwc} />
          <Line dataKey="FCF" stroke={COLORS.fcf} strokeWidth={1.5} dot={{ r: 2.5 }} />
          <Line dataKey="PV" stroke="#8b93a7" strokeWidth={1} strokeDasharray="3 3" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
