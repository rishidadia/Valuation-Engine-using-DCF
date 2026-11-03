/** Two-way sensitivity heatmap table (custom-rendered for exact cell styling). */
import { fmtMoney } from "../lib/format";
import type { SensitivityTable } from "../types/api";

export default function Heatmap({ table }: { table: SensitivityTable }) {
  const flat = table.matrix.flat().filter((v): v is number => v != null);
  const min = flat.length ? Math.min(...flat) : 0;
  const max = flat.length ? Math.max(...flat) : 1;
  const range = max - min || 1;

  const colorFor = (v: number | null) => {
    if (v == null) return { bg: "rgba(248,113,113,0.08)", fg: "#f87171" };
    const t = (v - min) / range;
    // dark neutral -> accent scale
    const alpha = 0.08 + t * 0.42;
    return { bg: `rgba(88,214,169,${alpha.toFixed(3)})`, fg: t > 0.55 ? "#eafff6" : "#cfd4dd" };
  };

  return (
    <div className="panel px-3 py-3">
      <div className="micro px-1 pb-2">{table.title}</div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-center">
          <thead>
            <tr>
              <th className="border border-line bg-ink-850 px-2 py-1.5 text-left">
                <span className="micro">{table.row_label} ↓ / {table.col_label} →</span>
              </th>
              {table.col_values.map((c, j) => (
                <th key={j} className="num border border-line bg-ink-850 px-2 py-1.5 text-[11px] text-muted">
                  {table.unit === "price" ? c.toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : c}
                  {table.key.includes("growth") ? "" : table.key === "wacc_vs_exit" ? "x" : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.row_values.map((r, i) => (
              <tr key={i}>
                <td className="num border border-line bg-ink-850 px-2 py-1.5 text-left text-[11px] text-muted">
                  {r.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")}
                  {table.key === "wacc_vs_growth" || table.key === "wacc_vs_exit" ? "" : ""}
                </td>
                {table.matrix[i].map((v, j) => {
                  const { bg, fg } = colorFor(v);
                  const isBase =
                    table.base_row != null && table.base_col != null &&
                    Math.abs(table.row_values[i] - table.base_row) < 1e-9 &&
                    Math.abs(table.col_values[j] - table.base_col) < 1e-9;
                  return (
                    <td
                      key={j}
                      className="num border border-line px-2 py-1.5 text-[11.5px]"
                      style={{ background: bg, color: fg, outline: isBase ? "1px solid #58d6a9" : undefined }}
                      title={v == null ? "Undefined: WACC ≤ terminal growth" : undefined}
                    >
                      {v == null ? "n/a" : fmtMoney(v, "$", 2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note && <p className="px-1 pt-2 text-[10.5px] text-dim">{table.note}</p>}
    </div>
  );
}
