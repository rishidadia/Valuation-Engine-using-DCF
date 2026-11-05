/** Typed API client with structured error propagation (never swallows failures). */
import type { IngestResponse, ValuationView } from "../types/api";

const BASE = "/api";

export class ApiError extends Error {
  code: string;
  hint?: string;
  status: number;

  constructor(status: number, code: string, message: string, hint?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.hint = hint;
  }
}

/** Optional key for deployments that set DCF_API_KEYS (localStorage, not bundled). */
function apiKey(): string | null {
  try {
    return localStorage.getItem("dcf_api_key");
  } catch {
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const key = apiKey();
  // FormData must set its own multipart boundary — forcing JSON here would
  // make Excel uploads unparseable on the server.
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(key ? { "X-API-Key": key } : {}),
        ...(init?.headers || {}),
      },
    });
  } catch (err) {
    throw new ApiError(
      0,
      "network_error",
      `Cannot reach the DCF labs API (${String(err)}).`,
      "Is the backend running on port 8000?"
    );
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const d = (data ?? {}) as Record<string, unknown>;
    const detail = (d.detail ?? d) as Record<string, unknown>;
    const code = String(detail?.error ?? "error");
    const message = String(detail?.detail ?? res.statusText ?? "Request failed");
    const hint = detail?.hint ? String(detail.hint) : undefined;
    throw new ApiError(res.status, code, message, hint);
  }
  return data as T;
}

export const api = {
  // ingest
  ingestPublic: (body: { ticker: string; name?: string; peer_tickers?: string[]; include_comparables?: boolean }) =>
    request<IngestResponse>("/company/public", { method: "POST", body: JSON.stringify(body) }),

  uploadExcel: (file: File, companyName?: string,
                opts?: { currency?: string; fiscal_year_end?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (companyName) fd.append("company_name", companyName);
    if (opts?.currency) fd.append("currency", opts.currency);
    if (opts?.fiscal_year_end) fd.append("fiscal_year_end", opts.fiscal_year_end);
    return request<IngestResponse>("/company/upload", { method: "POST", body: fd });
  },

  getCompany: (id: string) =>
    request<{
      company: IngestResponse["review"]["company"];
      review: IngestResponse["review"];
      mapping_notes: { field: string; mapped_from: string; confidence: number; ambiguous: boolean }[];
      excel_values: Record<string, number>;
      debt_instruments: { name: string; amount: number; rate: number }[];
    }>(`/company/${id}`),

  patchMetrics: (id: string, overrides: { metric: string; value: number | null; period?: string }[]) =>
    request<IngestResponse["review"]>(`/company/${id}/metrics`, {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    }),

  // valuation
  runValuation: (body: {
    company_id: string;
    overrides?: Record<string, number>;
    options?: Partial<ValuationOptionsBody>;
    scenario?: string;
  }) => request<ValuationView>("/valuation/run", { method: "POST", body: JSON.stringify(body) }),

  getValuation: (id: string) => request<ValuationView>(`/valuation/${id}`),

  postAssumptions: (
    id: string,
    body: { overrides?: Record<string, number>; clear?: string[]; options?: Partial<ValuationOptionsBody>; recompute?: boolean }
  ) => request<ValuationView>(`/valuation/${id}/assumptions`, { method: "POST", body: JSON.stringify(body) }),

  postScenarios: (id: string, body: { active: string; overrides?: Record<string, number>; recompute?: boolean }) =>
    request<ValuationView>(`/valuation/${id}/scenarios`, { method: "POST", body: JSON.stringify(body) }),

  getSection: <T>(id: string, section: string) => request<T>(`/valuation/${id}/${section}`),

  listValuations: () =>
    request<{ valuations: { id: string; name: string | null; ticker: string | null; status: string; implied_share_price: number | null; created_at: string | null }[] }>(
      "/valuations"
    ),

  health: () => request<{ status: string; app: string; database: string; providers: string[] }>("/health"),
};

export interface ValuationOptionsBody {
  cost_of_equity_method: "capm" | "manual";
  beta_method: "market" | "comparables" | "manual";
  cost_of_debt_method: "interest_bearing" | "instruments" | "manual";
  tax_rate_method: "historical_effective" | "statutory" | "manual";
  capital_structure_method: "current" | "target" | "manual";
  terminal_method: "perpetuity_growth" | "exit_multiple";
  beta_aggregation: "median" | "mean";
  discount_convention: "end" | "mid";
  forecast_years: number;
  peer_tickers: string[];
  run_comparables: boolean;
  run_sensitivity: boolean;
}
