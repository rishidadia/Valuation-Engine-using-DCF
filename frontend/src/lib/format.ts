/** Number formatting + provenance helpers for financial display. */

export function fmtMoney(v: number | null | undefined, currency = "", digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "−" : "";
  const abs = Math.abs(v);
  const compact =
    abs >= 1e12
      ? `${(abs / 1e12).toFixed(2)}T`
      : abs >= 1e9
      ? `${(abs / 1e9).toFixed(2)}B`
      : abs >= 1e6
      ? `${(abs / 1e6).toFixed(1)}M`
      : abs >= 1e3
      ? `${(abs / 1e3).toFixed(1)}K`
      : abs.toFixed(digits);
  return `${sign}${currency}${compact}`;
}

export function fmtFull(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtSigned(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(digits)}%`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function fmtValue(v: number | null | undefined, unit: string, currency?: string | null): string {
  if (v === null || v === undefined) return "—";
  switch (unit) {
    case "percent":
      return fmtPct(v);
    case "multiple":
      return `${fmtNum(v, 2)}x`;
    case "count":
      return fmtFull(v);
    case "ratio":
      return fmtNum(v, 3);
    default:
      return fmtMoney(v, currency ?? "");
  }
}

export const SOURCE_COLORS: Record<string, string> = {
  PUBLIC_API: "text-sky-300 border-sky-800/60 bg-sky-950/40",
  UPLOADED_EXCEL: "text-emerald-300 border-emerald-800/60 bg-emerald-950/40",
  USER_INPUT: "text-amber-300 border-amber-800/60 bg-amber-950/40",
  USER_OVERRIDE: "text-orange-300 border-orange-700/60 bg-orange-950/50",
  MODEL_CALCULATION: "text-violet-300 border-violet-800/60 bg-violet-950/40",
  MODEL_ASSUMPTION: "text-zinc-300 border-zinc-700/60 bg-zinc-900/60",
};

export const STATUS_COLORS: Record<string, string> = {
  Retrieved: "text-sky-300",
  "User Data": "text-emerald-300",
  Calculated: "text-violet-300",
  Estimated: "text-zinc-300",
  Override: "text-orange-300",
  Missing: "text-down",
};

export const AUDIT_COLORS: Record<string, string> = {
  PASS: "text-up border-up/40 bg-up/10",
  WARNING: "text-warn border-warn/40 bg-warn/10",
  FAIL: "text-down border-down/40 bg-down/10",
};

export function tipFor(sv: {
  source?: string; source_type?: string; period?: string | null;
  source_url?: string | null; retrieved_at?: string | null;
  note?: string | null; cell_ref?: string | null; status?: string;
}): string {
  const lines = [
    `Source: ${sv.source ?? "—"}`,
    `Type: ${(sv.source_type ?? "—").replace(/_/g, " ")}`,
    sv.period ? `Period: ${sv.period}` : null,
    sv.retrieved_at ? `Retrieved: ${sv.retrieved_at}` : null,
    sv.cell_ref ? `Cell: ${sv.cell_ref}` : null,
    sv.note ? `Note: ${sv.note}` : null,
    sv.source_url ? `URL: ${sv.source_url}` : null,
  ].filter(Boolean);
  return lines.join("\n");
}
