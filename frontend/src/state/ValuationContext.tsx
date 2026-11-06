/** Global valuation state: ingest -> run -> sections -> overrides -> scenarios. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "../services/api";
import type { DataReview, IngestResponse, ValuationView } from "../types/api";

interface Ctx {
  companyId: string | null;
  valuationId: string | null;
  view: ValuationView | null;
  review: DataReview | null;
  mode: "public" | "excel" | null;
  loading: boolean;
  busy: boolean;
  error: ApiError | null;
  notice: string | null;
  setIngest: (r: IngestResponse) => void;
  run: (overrides?: Record<string, number>, options?: Record<string, unknown>) => Promise<boolean>;
  reload: () => Promise<void>;
  applyAssumptions: (
    overrides: Record<string, number>,
    clear?: string[],
    options?: Record<string, unknown>
  ) => Promise<void>;
  applyScenario: (active: string, overrides?: Record<string, number>) => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

const ValuationCtx = createContext<Ctx | null>(null);

const LS_COMPANY = "dcflabs.companyId";
const LS_VALUATION = "dcflabs.valuationId";
const LS_MODE = "dcflabs.mode";
const LS_REVIEW = "dcflabs.review";

export function ValuationProvider({ children }: { children: ReactNode }) {
  const [companyId, setCompanyId] = useState<string | null>(() => localStorage.getItem(LS_COMPANY));
  const [valuationId, setValuationId] = useState<string | null>(() => localStorage.getItem(LS_VALUATION));
  const [mode, setMode] = useState<"public" | "excel" | null>(() =>
    (localStorage.getItem(LS_MODE) as "public" | "excel" | null) ?? null
  );
  const [review, setReview] = useState<DataReview | null>(() => {
    try {
      const raw = sessionStorage.getItem(LS_REVIEW);
      return raw ? (JSON.parse(raw) as DataReview) : null;
    } catch {
      return null;
    }
  });
  const [view, setView] = useState<ValuationView | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const vid = localStorage.getItem(LS_VALUATION);
    if (!vid) return;
    setLoading(true);
    try {
      const v = await api.getValuation(vid);
      setView(v);
      setValuationId(vid);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        localStorage.removeItem(LS_VALUATION);
        setValuationId(null);
      } else {
        setError(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setIngest = useCallback((r: IngestResponse) => {
    setCompanyId(r.company_id);
    setMode(r.mode);
    setReview(r.review);
    localStorage.setItem(LS_COMPANY, r.company_id);
    localStorage.setItem(LS_MODE, r.mode);
    sessionStorage.setItem(LS_REVIEW, JSON.stringify(r.review));
    // New or corrected data invalidates the previous valuation: showing an old
    // valuation next to new numbers is exactly how wrong conclusions happen.
    localStorage.removeItem(LS_VALUATION);
    setValuationId(null);
    setView(null);
    setError(null);
  }, []);

  const run = useCallback(
    async (overrides?: Record<string, number>, options?: Record<string, unknown>) => {
      const cid = companyId ?? localStorage.getItem(LS_COMPANY);
      if (!cid) {
        setError(new ApiError(0, "no_company", "No company ingested yet."));
        return false;
      }
      setBusy(true);
      setError(null);
      setNotice("Running agent workflow…");
      try {
        const v = await api.runValuation({ company_id: cid, overrides, options });
        setView(v);
        setValuationId(v.summary.id ?? null);
        if (v.summary.id) localStorage.setItem(LS_VALUATION, v.summary.id);
        setNotice(
          v.summary.status === "blocked"
            ? "Valuation computed but BLOCKED by audit — review the Audit section."
            : "Valuation complete."
        );
        return true;
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
        return false;
      } finally {
        setBusy(false);
        setNotice(null);
      }
    },
    [companyId]
  );

  const applyAssumptions = useCallback(
    async (overrides: Record<string, number>, clear: string[] = [], options?: Record<string, unknown>) => {
      const vid = valuationId ?? localStorage.getItem(LS_VALUATION);
      if (!vid) return;
      setBusy(true);
      setError(null);
      try {
        const v = await api.postAssumptions(vid, { overrides, clear, options, recompute: true });
        setView(v);
        setNotice("Valuation recomputed with your overrides.");
        window.setTimeout(() => setNotice(null), 2500);
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
      } finally {
        setBusy(false);
      }
    },
    [valuationId]
  );

  const applyScenario = useCallback(
    async (active: string, overrides: Record<string, number> = {}) => {
      const vid = valuationId ?? localStorage.getItem(LS_VALUATION);
      if (!vid) return;
      setBusy(true);
      setError(null);
      try {
        const v = await api.postScenarios(vid, { active, overrides, recompute: true });
        setView(v);
        setNotice(`Scenario switched: ${active}`);
        window.setTimeout(() => setNotice(null), 2000);
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
      } finally {
        setBusy(false);
      }
    },
    [valuationId]
  );

  const reset = useCallback(() => {
    localStorage.removeItem(LS_COMPANY);
    localStorage.removeItem(LS_VALUATION);
    sessionStorage.removeItem(LS_REVIEW);
    setCompanyId(null);
    setValuationId(null);
    setView(null);
    setReview(null);
    setMode(null);
    setError(null);
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      companyId, valuationId, view, review, mode, loading, busy, error, notice,
      setIngest, run, reload, applyAssumptions, applyScenario,
      clearError: () => setError(null), reset,
    }),
    [companyId, valuationId, view, review, mode, loading, busy, error, notice,
     setIngest, run, reload, applyAssumptions, applyScenario, reset]
  );

  return <ValuationCtx.Provider value={value}>{children}</ValuationCtx.Provider>;
}

export function useValuation(): Ctx {
  const ctx = useContext(ValuationCtx);
  if (!ctx) throw new Error("useValuation must be used inside ValuationProvider");
  return ctx;
}
