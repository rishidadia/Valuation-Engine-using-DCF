/** AUDIT — full check list, blocking issues, data sources. */
import { AuditBadge, ContextLabel, SectionHeader, SourceBadge } from "../components/ui";
import { useValuation } from "../state/ValuationContext";

export default function AuditPage() {
  const { view } = useValuation();
  const audit = view?.audit;

  if (!audit) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No audit yet — run a valuation first.</div>;
  }

  const groups = {
    critical: audit.checks.filter((c) => c.severity === "critical"),
    warning: audit.checks.filter((c) => c.status === "WARNING"),
    info: audit.checks.filter((c) => c.status === "PASS"),
  };

  return (
    <div>
      <SectionHeader
        title="Audit"
        subtitle="An independent health-check of the whole valuation — every number is re-verified before the report is finalised."
        right={<AuditBadge status={audit.status} />}
      />

      <ContextLabel
        items={[
          { k: "Whose numbers", v: view?.company ? `every figure in ${view.company.name}'s valuation above` : "every figure in this valuation" },
          { k: "What is checked", v: "data completeness, statement ties, WACC sanity, terminal-value rules, cash-flow formulas, double counting" },
        ]}
      />

      {!audit.can_finalize && (
        <div className="mb-5 border border-down/40 bg-down/5 px-4 py-3">
          <div className="micro text-down">Blocking issues — valuation cannot be marked complete</div>
          <ul className="mt-1.5 space-y-1 text-[12.5px] text-[#f8d4d4]">
            {audit.blocking_issues.map((b, i) => <li key={i}>✕ {b}</li>)}
          </ul>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Stat label="PASS" value={groups.info.length} tone="text-up" />
        <Stat label="WARNING" value={groups.warning.length} tone="text-warn" />
        <Stat label="FAIL (blocking)" value={groups.critical.length} tone="text-down" />
      </div>

      <div className="mt-5 panel overflow-x-auto">
        <div className="panel-header">
          <span className="micro">All checks</span>
          <span className="text-[10px] text-dim">{audit.checks.length} checks executed</span>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["", "Check", "Detail", "Severity"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {audit.checks.map((c, i) => (
              <tr key={i} className="row-hover">
                <td className="px-3 py-2">
                  <span className={`num text-[12px] ${
                    c.status === "PASS" ? "text-up" : c.status === "WARNING" ? "text-warn" : "text-down"
                  }`}>
                    {c.status === "PASS" ? "✓" : c.status === "WARNING" ? "⚠" : "✕"}
                  </span>
                </td>
                <td className="px-3 py-2 text-[12.5px] text-[#dfe3ea] whitespace-nowrap">{c.name}</td>
                <td className="px-3 py-2 text-[12px] text-muted">{c.detail}</td>
                <td className="px-3 py-2 text-[11px] text-dim uppercase">{c.severity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-5 panel px-4 py-4">
        <div className="micro mb-3">Data sources — every number traces back to one of these</div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Source", "Type", "Retrieved", "Metrics", "Link"].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {view?.sources?.map((s) => (
              <tr key={s.id} className="row-hover">
                <td className="px-3 py-2 text-[12.5px] text-[#dfe3ea]">{s.name}</td>
                <td className="px-3 py-2"><SourceBadge type={s.source_type} /></td>
                <td className="num px-3 py-2 text-[11.5px] text-muted">{s.retrieved_at ?? "—"}</td>
                <td className="px-3 py-2 text-[11px] text-dim max-w-[320px] truncate" title={s.metrics.join(", ")}>
                  {s.metrics.slice(0, 8).join(", ")}
                  {s.metrics.length > 8 ? "…" : ""}
                </td>
                <td className="px-3 py-2">
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer" className="text-[11.5px] text-accent hover:underline">
                      open ↗
                    </a>
                  ) : (
                    <span className="text-[11px] text-dim">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="micro">{label}</div>
      <div className={`num mt-1 text-[20px] ${tone}`}>{value}</div>
    </div>
  );
}
