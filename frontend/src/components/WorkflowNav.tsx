/** Workflow navigation strip: DATA → ASSUMPTIONS → … → REPORT */
import { NavLink, useLocation } from "react-router-dom";

const STEPS = [
  { key: "data", label: "DATA" },
  { key: "assumptions", label: "ASSUMPTIONS" },
  { key: "forecast", label: "FORECAST" },
  { key: "wacc", label: "WACC" },
  { key: "fcf", label: "FCF" },
  { key: "dcf", label: "DCF" },
  { key: "sensitivity", label: "SENSITIVITY" },
  { key: "scenarios", label: "SCENARIOS" },
  { key: "comparables", label: "COMPS" },
  { key: "audit", label: "AUDIT" },
  { key: "report", label: "REPORT" },
];

export default function WorkflowNav() {
  const { pathname } = useLocation();
  return (
    <nav className="border-b border-line bg-ink-900/80 backdrop-blur sticky top-0 z-40">
      <div className="mx-auto flex max-w-[1440px] items-center gap-1 overflow-x-auto px-4 py-2">
        {STEPS.map((s, i) => {
          const active = pathname.includes(`/workspace/${s.key}`);
          return (
            <span key={s.key} className="flex items-center shrink-0">
              <NavLink
                to={`/workspace/${s.key}`}
                className={`px-2.5 py-1 text-[10px] tracking-widest border transition-colors duration-150 ${
                  active
                    ? "border-accent-dim text-accent bg-accent/10"
                    : "border-transparent text-dim hover:text-muted hover:border-line"
                }`}
              >
                {s.label}
              </NavLink>
              {i < STEPS.length - 1 && <span className="px-1 text-[9px] text-ink-600">→</span>}
            </span>
          );
        })}
      </div>
    </nav>
  );
}
