/** Agent Activity panel — status, action, result, warnings, sources. No CoT. */
import type { AgentRun } from "../types/api";

const ICONS: Record<string, { glyph: string; cls: string }> = {
  success: { glyph: "✓", cls: "text-up" },
  warning: { glyph: "✓", cls: "text-warn" },
  failed: { glyph: "✕", cls: "text-down" },
  skipped: { glyph: "–", cls: "text-dim" },
  running: { glyph: "•", cls: "text-accent animate-pulse" },
  pending: { glyph: "•", cls: "text-dim" },
};

export default function AgentActivity({ agents }: { agents: AgentRun[] }) {
  if (!agents?.length) return null;
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="micro">Agent Activity</span>
        <span className="text-[10px] text-dim">{agents.length} agents</span>
      </div>
      <ul className="divide-y divide-line">
        {agents.map((a) => {
          const icon = ICONS[a.status] ?? ICONS.pending;
          return (
            <li key={a.key} className="px-4 py-2.5">
              <div className="flex items-start gap-2.5">
                <span className={`num mt-[1px] w-3 shrink-0 text-center ${icon.cls}`}>{icon.glyph}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-[12.5px] text-[#dfe3ea]">{a.agent}</span>
                    <span className="num text-[10px] text-dim">
                      {a.duration_ms != null ? `${a.duration_ms}ms` : ""}
                      {a.llm_used ? " · LLM" : ""}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11.5px] leading-relaxed text-muted break-words">{a.result}</div>
                  {a.warnings?.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {a.warnings.slice(0, 3).map((w, i) => (
                        <li key={i} className="text-[11px] text-warn/90 break-words">⚠ {w}</li>
                      ))}
                    </ul>
                  )}
                  {a.sources?.length > 0 && (
                    <div className="mt-1 text-[10px] text-dim">sources: {a.sources.slice(0, 3).join(" · ")}</div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
