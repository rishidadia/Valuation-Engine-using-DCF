/** Shared UI primitives — thin borders, monospace numerics, restrained accents. */
import type { ReactNode } from "react";
import { AUDIT_COLORS, SOURCE_COLORS, STATUS_COLORS } from "../lib/format";
import type { CheckStatus, SourceType, ValueStatus } from "../types/api";

export function SourceBadge({ type }: { type: SourceType | string }) {
  const cls = SOURCE_COLORS[type] ?? SOURCE_COLORS.MODEL_ASSUMPTION;
  return (
    <span className={`border px-1.5 py-[1px] text-[9px] uppercase tracking-widest ${cls}`}>
      {String(type).replace(/_/g, " ")}
    </span>
  );
}

export function StatusText({ status }: { status: ValueStatus | string }) {
  const cls = STATUS_COLORS[status] ?? "text-muted";
  return <span className={`text-[11px] ${cls}`}>{status}</span>;
}

export function AuditBadge({ status }: { status: CheckStatus }) {
  return (
    <span className={`border px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest ${AUDIT_COLORS[status]}`}>
      {status}
    </span>
  );
}

export function SectionHeader({
  title, subtitle, right,
}: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      <div>
        <h1 className="text-lg font-medium tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-[12px] text-muted">{subtitle}</p>}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

export function StatTile({
  label, value, sub, tone = "default", tip,
}: { label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "up" | "down" | "warn"; tip?: string }) {
  const toneCls =
    tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "warn" ? "text-warn" : "text-white";
  return (
    <div className={`panel px-4 py-3 ${tip ? "tip" : ""}`} data-tip={tip}>
      <div className="micro">{label}</div>
      <div className={`num mt-1.5 text-[19px] ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function ErrorBanner({
  message, hint, onDismiss,
}: { message: string; hint?: string; onDismiss?: () => void }) {
  return (
    <div className="mb-4 border border-down/40 bg-down/5 px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="micro text-down">Error</div>
          <div className="mt-1 text-[13px] text-[#f8d4d4]">{message}</div>
          {hint && <div className="mt-1 text-[12px] text-muted">{hint}</div>}
        </div>
        {onDismiss && (
          <button onClick={onDismiss} className="text-dim hover:text-white" aria-label="Dismiss">
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

export function Notice({ text }: { text: string }) {
  return (
    <div className="mb-4 border border-accent-dim/50 bg-accent/5 px-4 py-2 text-[12px] text-accent animate-fade-in">
      {text}
    </div>
  );
}

export function Spinner({ label = "Working" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[12px] text-muted">
      <span className="h-3 w-3 animate-spin rounded-full border border-accent-dim border-t-transparent" />
      {label}…
    </span>
  );
}

export function Empty({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <div className="panel flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="text-[13px] text-muted">{text}</div>
      {action}
    </div>
  );
}

export function Radio({
  options, value, onChange, name,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  name: string;
}) {
  return (
    <div className="flex flex-wrap gap-3">
      {options.map((o) => (
        <label key={o.value} className="flex cursor-pointer items-center gap-1.5 text-[12px] text-muted hover:text-[#d6dae2]">
          <input
            type="radio"
            name={name}
            checked={value === o.value}
            onChange={() => onChange(o.value)}
            className="h-3 w-3 accent-[#58d6a9]"
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

export function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="micro">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function FormulaBox({ text, result }: { text: string; result?: string }) {
  return (
    <div className="border border-line bg-ink-850 px-3 py-2.5">
      <div className="num text-[12.5px] leading-relaxed text-[#cfd4dd] break-words">{text}</div>
      {result && <div className="num mt-1 text-[15px] text-accent">{result}</div>}
    </div>
  );
}

/** Plain-language context strip: whose data this is, and what is compared with what. */
export function ContextLabel({ items }: { items: { k: string; v: ReactNode }[] }) {
  return (
    <div className="mb-4 flex flex-wrap gap-x-7 gap-y-1.5 border border-line bg-ink-900 px-3.5 py-2 animate-fade-in">
      {items.map((it) => (
        <span key={it.k} className="flex items-baseline gap-2">
          <span className="micro shrink-0">{it.k}</span>
          <span className="text-[11.5px] text-[#cfd4dd]">{it.v}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * Head-to-head verdict: our estimated value vs the real market price.
 * Says plainly whether the company looks valued properly.
 */
export function VerdictStrip({
  implied, market, upside, basis,
}: {
  implied?: number | null;
  market?: number | null;
  upside?: number | null;
  basis?: string;
}) {
  if (implied == null) {
    return (
      <div className="mb-5 border border-line bg-ink-900 px-4 py-3">
        <div className="micro">Our estimate vs the market</div>
        <p className="mt-1 text-[12.5px] text-muted">
          No per-share estimate available{market ? " (shares outstanding missing)" : ""} —
          {market
            ? " the market price is shown for reference."
            : " this is a private company with no market price."}
        </p>
      </div>
    );
  }

  let verdict: string;
  let tone: "up" | "down" | "neutral";
  let verdictCls: string;
  if (market == null) {
    verdict = "Private company — no market price to compare against.";
    tone = "neutral";
    verdictCls = "text-[#dfe3ea]";
  } else if (upside != null && upside >= 0.1) {
    verdict = `The model values the company ${Math.abs(upside * 100).toFixed(1)}% ABOVE today's market price — on these assumptions the shares look UNDERVALUED.`;
    tone = "up";
    verdictCls = "text-up";
  } else if (upside != null && upside <= -0.1) {
    verdict = `The model values the company ${Math.abs(upside * 100).toFixed(1)}% BELOW today's market price — on these assumptions the shares look OVERVALUED.`;
    tone = "down";
    verdictCls = "text-down";
  } else {
    verdict = `The model and the market broadly agree — the estimate is within ±10% of today's market price.`;
    tone = "neutral";
    verdictCls = "text-[#dfe3ea]";
  }

  const big = "num text-[26px] leading-none tracking-tight";
  return (
    <div className="mb-5 border border-line bg-ink-900 px-4 py-4 animate-fade-in">
      <div className="micro">Comparing: our estimated value vs today's real market price</div>
      <div className="mt-3 flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <div className="text-[11px] text-dim">Our estimate (per share)</div>
          <div className={`${big} text-accent`}>
            {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(implied)}
          </div>
        </div>
        <div className="text-[20px] text-dim">↔</div>
        <div>
          <div className="text-[11px] text-dim">Market price (latest close)</div>
          <div className={`${big} text-white`}>
            {market != null
              ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(market)
              : "n/a"}
          </div>
        </div>
        {market != null && upside != null && (
          <div>
            <div className="text-[11px] text-dim">Difference</div>
            <div className={`${big} ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-warn"}`}>
              {upside >= 0 ? "+" : ""}{(upside * 100).toFixed(1)}%
            </div>
          </div>
        )}
      </div>
      <div className={`mt-3 border-t border-line pt-3 text-[13.5px] ${verdictCls}`}>
        {verdict}
      </div>
      {basis && <div className="mt-1.5 text-[11.5px] text-dim">{basis}</div>}
      <div className="mt-1.5 text-[11px] text-dim">
        Model estimate, highly sensitive to assumptions — not investment advice.
      </div>
    </div>
  );
}
