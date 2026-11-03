/** REPORT — verdict first, then conclusions, then the supporting detail. */
import { AuditBadge, SectionHeader, VerdictStrip } from "../components/ui";
import { fmtMoney, fmtSigned } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

const KIND_CLS: Record<string, string> = {
  FACT: "text-sky-300 border-sky-800/60",
  CALCULATION: "text-violet-300 border-violet-800/60",
  ASSUMPTION: "text-zinc-300 border-zinc-700",
  "USER OVERRIDE": "text-orange-300 border-orange-700",
  "MODEL ESTIMATE": "text-accent border-accent-dim/60",
  NARRATIVE: "text-muted border-line",
  WARNING: "text-warn border-warn/50",
};

/** Sections whose conclusions should be read before the detail. */
const CONCLUSION_HEADINGS = ["bottom line", "key risks"];

function isConclusion(heading: string): boolean {
  const h = heading.toLowerCase();
  return CONCLUSION_HEADINGS.some((c) => h.includes(c));
}

function kindCls(kind: string): string {
  return KIND_CLS[kind] ?? KIND_CLS.NARRATIVE;
}

export default function ReportPage() {
  const { view } = useValuation();
  const report = view?.report;
  const s = view?.summary;

  if (!report) {
    return (
      <div className="panel px-4 py-6 text-[13px] text-muted">
        No report yet — run a valuation first.
      </div>
    );
  }

  const download = () => {
    const blob = new Blob([report.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(view?.company.ticker ?? view?.company.name ?? "valuation").toLowerCase()}-valuation-report.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(view, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "valuation-full-audit.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  // conclusions first, everything else in original order
  const conclusions = report.sections.filter((sec) => isConclusion(sec.heading));
  const detail = report.sections.filter((sec) => !isConclusion(sec.heading));

  return (
    <div>
      <SectionHeader
        title={report.title}
        subtitle={report.subtitle}
        right={
          <>
            <AuditBadge status={report.audit_status} />
            <button className="btn-ghost !py-1.5" onClick={download}>↓ Markdown</button>
            <button className="btn-ghost !py-1.5" onClick={downloadJson}>↓ Full JSON</button>
          </>
        }
      />

      {/* 1 — the answer, up top, plain language */}
      <VerdictStrip
        implied={s?.implied_share_price}
        market={s?.current_share_price}
        upside={s?.upside_downside}
        basis={
          s
            ? `Enterprise value ${fmtMoney(s.enterprise_value)} · equity value ${fmtMoney(s.equity_value)} · WACC ${s.wacc != null ? `${(s.wacc * 100).toFixed(2)}%` : "n/a"} · difference vs market ${fmtSigned(s.upside_downside)}.`
            : undefined
        }
      />

      {/* 2 — conclusions: bottom line + key risks */}
      {conclusions.length > 0 && (
        <div className="mb-6 space-y-4 stagger">
          {conclusions.map((sec) => (
            <section
              key={sec.heading}
              className="panel px-5 py-4 border-accent-dim/40"
            >
              <div className="flex items-center gap-3 border-b border-line pb-2">
                <h2 className="text-[15px] text-white tracking-tight font-medium">
                  {stripNumber(sec.heading)}
                </h2>
                <span className={`border px-1.5 py-[1px] text-[9px] uppercase tracking-widest ${kindCls(sec.kind)}`}>
                  {sec.kind}
                </span>
              </div>
              <SectionBody sec={sec} emphasis />
            </section>
          ))}
        </div>
      )}

      <div className="mb-3 flex items-center gap-2">
        <span className="micro">The detail behind the conclusion</span>
        <span className="h-px flex-1 bg-line" />
      </div>

      {/* 3 — supporting detail, original order */}
      <div className="space-y-5">
        {detail.map((sec) => (
          <section key={sec.heading} className="panel px-5 py-4 animate-fade-in">
            <div className="flex items-center gap-3 border-b border-line pb-2">
              <h2 className="text-[14px] text-white tracking-tight">{sec.heading}</h2>
              <span className={`border px-1.5 py-[1px] text-[9px] uppercase tracking-widest ${kindCls(sec.kind)}`}>
                {sec.kind}
              </span>
            </div>
            <SectionBody sec={sec} />
          </section>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border border-line bg-ink-900 px-4 py-3">
        <span className="text-[11.5px] text-dim">
          Report generated {report.generated_at ? new Date(report.generated_at).toLocaleString() : ""}
          {report.llm_used ? " · narrative sections LLM-drafted, all numbers computed" : " · fully deterministic"}
        </span>
        <button className="btn-primary !py-1.5" onClick={download}>Export report</button>
      </div>
    </div>
  );
}

/** "1. Bottom Line — Is the Company Valued Properly?" → "Bottom Line — Is the Company Valued Properly?" */
function stripNumber(heading: string): string {
  return heading.replace(/^\d+\.\s*/, "");
}

/**
 * Renders a section body preserving order: consecutive bullet lines become a list,
 * other lines become paragraphs. Emphasised sections get larger type.
 */
function SectionBody({ sec, emphasis = false }: { sec: { body: string; table?: { columns: string[]; rows: (string | number | null)[][] } | null }; emphasis?: boolean }) {
  type Block = { type: "p" | "ul"; items: string[] };
  const blocks: Block[] = [];
  let lastWasBullet = false;
  for (const raw of (sec.body ?? "").split("\n")) {
    const t = raw.trim();
    if (!t) {
      lastWasBullet = false;
      continue;
    }
    if (t.startsWith("- ") || t.startsWith("• ")) {
      const item = t.replace(/^[-•]\s*/, "");
      if (lastWasBullet && blocks.length > 0) {
        blocks[blocks.length - 1].items.push(item);
      } else {
        blocks.push({ type: "ul", items: [item] });
      }
      lastWasBullet = true;
    } else if (lastWasBullet && blocks.length > 0 && raw.startsWith("  ")) {
      // indented continuation of the previous bullet
      const bl = blocks[blocks.length - 1];
      bl.items[bl.items.length - 1] += " " + t;
    } else {
      if (lastWasBullet && blocks.length > 0 && blocks[blocks.length - 1].type === "ul" && /^[A-Z][^:]{0,60}:$/.test(t)) {
        // a label line like "INTERPRETATION (…):" starts a new paragraph block
        blocks.push({ type: "p", items: [t] });
      } else if (blocks.length > 0 && blocks[blocks.length - 1].type === "p") {
        blocks[blocks.length - 1].items.push(t);
      } else {
        blocks.push({ type: "p", items: [t] });
      }
      lastWasBullet = false;
    }
  }

  return (
    <>
      {blocks.map((b, bi) =>
        b.type === "p" ? (
          <div
            key={bi}
            className={`mt-3 space-y-2 whitespace-pre-wrap leading-relaxed text-[#c9ced8] ${emphasis ? "text-[14px]" : "text-[12.5px]"}`}
          >
            {b.items.map((p, i) => (
              <p key={i} className={emphasis && bi === 0 && i === 0 ? "text-[15px] text-white" : ""}>{p}</p>
            ))}
          </div>
        ) : (
          <ul key={bi} className={`mt-2 space-y-1.5 ${emphasis ? "text-[13.5px]" : "text-[12.5px]"} text-[#c9ced8]`}>
            {b.items.map((item, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-accent shrink-0">▸</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        )
      )}
      {sec.table && sec.table.rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-line">
                {sec.table.columns.map((c) => (
                  <th key={c} className="micro px-2 py-1.5 font-normal">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line/70">
              {sec.table.rows.map((r, i) => (
                <tr key={i} className="row-hover">
                  {r.map((cell, j) => (
                    <td key={j} className={`px-2 py-1 text-[12px] ${j === 0 ? "text-[#dfe3ea]" : "num text-muted"}`}>
                      {cell == null ? "—" : String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
