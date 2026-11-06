/** DATA — ingest (Excel upload or ticker) + review table with corrections. */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { fmtFull, STATUS_COLORS } from "../lib/format";
import type { DataReview, IngestResponse } from "../types/api";
import { ContextLabel, ErrorBanner, SectionHeader, SourceBadge, Spinner } from "../components/ui";
import { useValuation } from "../state/ValuationContext";

export default function DataPage() {
  const [params, setParams] = useSearchParams();
  const mode = (params.get("mode") as "upload" | "public" | null) ?? "public";
  const { setIngest, run, busy, review, error, clearError, companyId, view } = useValuation();
  const [dirtyCorrections, setDirtyCorrections] = useState(false);
  const navigate = useNavigate();

  // Revenue is the one figure a DCF cannot invent: without it the backend audit
  // blocks the valuation, so the button is disabled here with the reason shown.
  const revenueMissing = Boolean(review && review.missing_critical.includes("revenue"));
  const latestPeriod = review?.periods.at(-1) ?? "the latest period";

  return (
    <div>
      <SectionHeader
        title="Data Review"
        subtitle="Step 1 — load the numbers (from a ticker or your own Excel file), check them here, then run the valuation."
        right={
          <div className="flex border border-line">
            {(["public", "upload"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setParams({ mode: m })}
                className={`px-3 py-1.5 text-[10px] tracking-widest transition-colors ${
                  mode === m ? "bg-accent/10 text-accent" : "text-dim hover:text-muted"
                }`}
              >
                {m === "public" ? "PUBLIC TICKER" : "EXCEL UPLOAD"}
              </button>
            ))}
          </div>
        }
      />

      {error && <ErrorBanner message={error.message} hint={error.hint} onDismiss={clearError} />}

      {mode === "public" ? <PublicForm onIngest={setIngest} busy={busy} /> : <UploadForm onIngest={setIngest} busy={busy} />}

      {review && (
        <ReviewTable
          key={review.company.name + review.periods.join()}
          review={review}
          companyId={companyId}
          onDirtyChange={setDirtyCorrections}
        />
      )}

      {review && !view && (
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <button
            className="btn-primary"
            disabled={busy || dirtyCorrections || revenueMissing}
            onClick={async () => {
              const ok = await run();
              if (ok) navigate("/workspace/assumptions");
            }}
          >
            {busy ? "Running agents…" : "Run valuation →"}
          </button>
          {revenueMissing ? (
            <span className="text-[12px] text-down">
              Revenue is missing for {latestPeriod} — enter it with <em>edit</em> and save before
              running. A valuation without revenue would be invented, not calculated.
            </span>
          ) : dirtyCorrections ? (
            <span className="text-[12px] text-warn">
              You have unsaved corrections — save them first, or the valuation runs on the old
              numbers.
            </span>
          ) : (
            <span className="text-[12px] text-dim">
              Takes the numbers above through forecast → WACC → cash flow → DCF → sensitivity →
              audit → report. A short progress window appears while it runs.
            </span>
          )}
        </div>
      )}
      {view && !review && (
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button className="btn-ghost" onClick={() => navigate("/workspace/assumptions")}>
            Continue to assumptions →
          </button>
          <span className="text-[12px] text-dim">
            A stored valuation for {view.company.name} is loaded. Fetch a ticker or upload a
            workbook above to replace these numbers.
          </span>
        </div>
      )}
      {review && view && (
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            className="btn-ghost"
            disabled={dirtyCorrections}
            onClick={() => navigate("/workspace/assumptions")}
          >
            Continue to assumptions →
          </button>
          <button className="btn-ghost" disabled={busy || dirtyCorrections || revenueMissing} onClick={() => void run()}>
            Re-run with the data above
          </button>
          <span className="text-[12px] text-dim">
            {dirtyCorrections
              ? "Save your corrections first — then re-run."
              : "A valuation already exists for these numbers — data changes require a re-run."}
          </span>
        </div>
      )}
    </div>
  );
}

function PublicForm({
  onIngest, busy,
}: { onIngest: (r: IngestResponse) => void; busy: boolean }) {
  const [ticker, setTicker] = useState("");
  const [market, setMarket] = useState<"US" | "IN">("US");
  const [peers, setPeers] = useState("");
  const [local, setLocal] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const [ingestAgents, setIngestAgents] = useState<IngestResponse["agents"]>([]);
  const isIndia = market === "IN";
  const cleanTicker = ticker.trim().toUpperCase();
  const tickerInvalid = cleanTicker !== "" && !/^[A-Z0-9][A-Z0-9.&-]{0,19}$/.test(cleanTicker);
  const bseOnly = /\.BO$/.test(cleanTicker);
  const canSubmit = cleanTicker !== "" && !tickerInvalid && !bseOnly && !busy && !pending;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setLocal(null);
    setPending(true);
    try {
      const peerList = peers.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
      const r = await api.ingestPublic({
        ticker: cleanTicker,
        market,
        peer_tickers: peerList,
        include_comparables: true,
      });
      setIngestAgents(r.agents);
      onIngest(r);
    } catch (err) {
      setLocal(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="panel px-4 py-4">
      {local && <ErrorBanner message={local.message} hint={local.hint} onDismiss={() => setLocal(null)} />}
      <div className="grid gap-4 sm:grid-cols-[150px_170px_1fr_auto] sm:items-end">
        <label className="block">
          <span className="micro">Ticker</span>
          <input
            className="input mt-1 uppercase"
            placeholder={isIndia ? "RELIANCE" : "AAPL"}
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onBlur={() => setTicker((t) => t.trim())}
            maxLength={20}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={tickerInvalid || bseOnly}
            disabled={pending}
          />
        </label>
        <label className="block">
          <span className="micro">Market</span>
          <select
            className="input mt-1"
            value={market}
            onChange={(e) => {
              setMarket(e.target.value as "US" | "IN");
              // peers are market-specific; never send SEC peers to NSE (or vice versa)
              setPeers("");
            }}
            disabled={pending}
          >
            <option value="US">United States (SEC)</option>
            <option value="IN">India (NSE)</option>
          </select>
        </label>
        <label className="block">
          <span className="micro">Peer tickers (optional — comma separated)</span>
          <input
            className="input mt-1"
            placeholder={isIndia ? "INFY, HCLTECH, WIPRO" : "MSFT, GOOGL, META"}
            value={peers}
            onChange={(e) => setPeers(e.target.value)}
            disabled={pending}
          />
        </label>
        <button className="btn-primary h-[34px]" disabled={!canSubmit}>
          {pending ? (
            <>
              <span className="h-3 w-3 animate-spin rounded-full border border-accent-dim border-t-transparent" />
              Fetching…
            </>
          ) : (
            "Fetch data"
          )}
        </button>
      </div>
      {(tickerInvalid || bseOnly) && (
        <p className="mt-2 text-[11.5px] text-down">
          {bseOnly
            ? `${cleanTicker} is a BSE code. Use the NSE symbol instead (e.g. ${cleanTicker.replace(/\.BO$/, "")}) with Market set to India (NSE).`
            : "A ticker is letters and numbers with optional dots or dashes — e.g. AAPL, BRK.B, RELIANCE.NS."}
        </p>
      )}
      {pending && (
        <p className="mt-3 text-[12px] text-accent animate-fade-in">
          {isIndia
            ? `Contacting NSE India for ${ticker.trim().toUpperCase()} — annual XBRL filings, bhavcopy close and NIFTY 50 beta. This can take a few seconds.`
            : `Contacting SEC EDGAR, Yahoo Finance and FRED for ${ticker.trim().toUpperCase()} — usually a few seconds.`}{" "}
          Please don't close this page.
        </p>
      )}
      {!pending && (
        <p className="mt-3 text-[11.5px] text-dim">
          {isIndia ? (
            <>
              Where the numbers come from: NSE India annual filings (XBRL), the official NSE
              bhavcopy close and NSE NIFTY 50 history for beta (or Zerodha Kite when
              configured), risk-free rate (India 10Y G-Sec via FRED). Nothing is scraped from
              yfinance; anything we can't find is left blank for you to fill in.
            </>
          ) : (
            <>
              Where the numbers come from: company filings (SEC EDGAR), share price and beta
              (Yahoo Finance), risk-free rate (US Treasury via FRED). Anything we can't find is
              left blank for you to fill in — never guessed.
            </>
          )}
        </p>
      )}
      {ingestAgents.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-line pt-3">
          {ingestAgents.map((a) => (
            <li key={a.key} className="text-[11.5px] text-muted">
              <span className={a.status === "failed" ? "text-down" : "text-up"}>●</span>{" "}
              <span className="text-[#dfe3ea]">{a.agent}</span> — {a.result}
              {a.warnings.slice(0, 2).map((w, i) => (
                <span key={i} className="block pl-3 text-warn/90">⚠ {w}</span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}

function UploadForm({ onIngest, busy }: { onIngest: (r: IngestResponse) => void; busy: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [local, setLocal] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setLocal(null);
    setPending(true);
    try {
      const r = await api.uploadExcel(file, name || undefined);
      onIngest(r);
    } catch (err) {
      setLocal(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="panel px-4 py-4">
      {local && <ErrorBanner message={local.message} hint={local.hint} onDismiss={() => setLocal(null)} />}
      <div className="grid gap-4 sm:grid-cols-[1fr_220px_auto] sm:items-end">
        <div>
          <span className="micro">Workbook (.xlsx, max 10 MB)</span>
          <div
            className="mt-1 flex cursor-pointer items-center gap-3 border border-dashed border-line bg-ink-850 px-3 py-2.5 hover:border-accent-dim/60"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0];
              if (f) setFile(f);
            }}
          >
            <span className="text-accent">⬆</span>
            <span className="text-[12.5px] text-muted">
              {file ? file.name : "Drop a workbook or click to browse"}
            </span>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <label className="block">
          <span className="micro">Company name</span>
          <input className="input mt-1" placeholder="Acme Manufacturing" value={name}
                 onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="btn-primary h-[34px]" disabled={busy || pending || !file}>
          {pending ? (
            <>
              <span className="h-3 w-3 animate-spin rounded-full border border-accent-dim border-t-transparent" />
              Reading workbook…
            </>
          ) : (
            "Upload & map"
          )}
        </button>
      </div>
      {pending && (
        <p className="mt-3 text-[12px] text-accent animate-fade-in">
          Reading your workbook — detecting sheets, labels and periods…
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-4 text-[11.5px]">
        <a href="/api/company/template" className="text-accent hover:underline">
          ↓ Download Excel template
        </a>
        <span className="text-dim">
          Sheets are detected heuristically — no fixed layout required. Mappings are shown below and
          can be corrected.
        </span>
      </div>
    </form>
  );
}

function ReviewTable({
  review, companyId, onDirtyChange,
}: { review: DataReview; companyId: string | null; onDirtyChange?: (dirty: boolean) => void }) {
  const rows = review.rows;
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [local, setLocal] = useState<ApiError | null>(null);
  const { setIngest, mode } = useValuation();

  // Tell the page about unsaved corrections so it can stop a run that would use
  // the old numbers.
  useEffect(() => {
    onDirtyChange?.(Object.keys(edits).length > 0);
  }, [edits, onDirtyChange]);

  const missing = rows.filter((r) => r.status === "Missing");
  const total = rows.length;

  const save = async () => {
    if (!companyId) return;
    setSaving(true);
    setLocal(null);
    try {
      const overrides = Object.entries(edits)
        .filter(([, v]) => v !== "")
        .map(([key, v]) => ({ metric: key, value: Number(v), period: review.periods.at(-1) }));
      await api.patchMetrics(companyId, overrides);
      // refresh review inside stored ingest state
      const fresh = await api.getCompany(companyId);
      setIngest({
        company_id: companyId,
        mode: mode ?? "public",
        review: fresh.review,
        warnings: [],
        agents: [],
      });
      setEdits({});
    } catch (err) {
      setLocal(err instanceof ApiError ? err : new ApiError(0, "error", String(err)));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-6">
      <ContextLabel
        items={[
          { k: "Whose data", v: `${review.company.name}${review.company.ticker ? ` (${review.company.ticker})` : ""}` },
          { k: "Where from", v: review.company.provider === "excel" ? "Your uploaded workbook" : review.company.provider === "nse_india" ? "NSE India filings + NSE market data" : "Official SEC filings + market data" },
          { k: "Periods", v: review.periods.join(", ") || "—" },
          { k: "Currency", v: review.company.currency || "n/a" },
          { k: "What next", v: "Check these figures, correct anything wrong, then run the valuation" },
        ]}
      />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-4">
          <h2 className="text-[13px] uppercase tracking-widest text-muted">Every figure, and where it came from</h2>
          <span className="num text-[11px] text-dim">{total} fields</span>
          {missing.length > 0 && (
            <span className="text-[11px] text-down">{missing.length} critical missing</span>
          )}
        </div>
        {Object.keys(edits).length > 0 && (
          <button className="btn-primary !py-1" onClick={save} disabled={saving}>
            {saving ? "Saving…" : `Save ${Object.keys(edits).length} correction(s)`}
          </button>
        )}
      </div>

      {local && <ErrorBanner message={local.message} hint={local.hint} onDismiss={() => setLocal(null)} />}

      {review.warnings.length > 0 && (
        <div className="mb-3 border border-warn/30 bg-warn/5 px-3 py-2">
          <div className="micro text-warn">Ingestion warnings</div>
          <ul className="mt-1 space-y-0.5 text-[11.5px] text-warn/90">
            {review.warnings.slice(0, 8).map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-line">
              {["Field", "Value", "Period", "Source", "Type", "Status", ""].map((h) => (
                <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.key} className={`row-hover ${r.status === "Missing" ? "bg-down/[0.04]" : ""}`}>
                <td className="px-3 py-1.5 text-[12.5px] text-[#dfe3ea] whitespace-nowrap">
                  {r.field}
                  {r.critical && <span className="ml-1 text-down">*</span>}
                </td>
                <td className="px-3 py-1.5">
                  {edits[r.key] !== undefined ? (
                    <input
                      className="input !py-0.5 !text-[12px] w-36"
                      value={edits[r.key]}
                      onChange={(e) => setEdits({ ...edits, [r.key]: e.target.value })}
                      autoFocus
                    />
                  ) : (
                    <span className={`num text-[12.5px] ${r.status === "Missing" ? "text-down" : "text-white"}`}>
                      {r.display ?? fmtFull(r.value)}
                    </span>
                  )}
                </td>
                <td className="num px-3 py-1.5 text-[11.5px] text-muted">{r.period ?? "—"}</td>
                <td className="px-3 py-1.5 text-[11.5px] text-muted max-w-[260px] truncate"
                    title={`${r.source}${r.cell_ref ? ` (${r.cell_ref})` : ""}`}>
                  {r.source}
                  {r.cell_ref && <span className="ml-1 text-dim">[{r.cell_ref}]</span>}
                </td>
                <td className="px-3 py-1.5"><SourceBadge type={r.source_type} /></td>
                <td className="px-3 py-1.5">
                  <span className="text-[11px]" style={{ color: `var(--x)` }}>
                    <span className={STATUS_COLORS[r.status] ?? "text-muted"}>{r.status}</span>
                  </span>
                </td>
                <td className="px-3 py-1.5 text-right">
                  <button
                    className="text-[11px] text-dim hover:text-accent"
                    onClick={() =>
                      setEdits((prev) =>
                        prev[r.key] !== undefined
                          ? Object.fromEntries(Object.entries(prev).filter(([k]) => k !== r.key))
                          : { ...prev, [r.key]: r.value != null ? String(r.value) : "" }
                      )
                    }
                  >
                    {edits[r.key] !== undefined ? "cancel" : "edit"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {missing.length > 0 && (
        <div className="mt-3 border border-down/30 bg-down/5 px-3 py-2">
          <div className="micro text-down">Missing — will not be invented</div>
          <p className="mt-1 text-[11.5px] text-[#f3c9c9]">
            {missing.map((m) => m.field).join(", ")}. Enter values with <em>edit</em>, or the
            affected outputs (e.g. implied share price) will be reported as unavailable.
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] text-dim">
        <span className="micro">Badge legend</span>
        <span><SourceBadge type="PUBLIC API" /> pulled from a public source</span>
        <span><SourceBadge type="MODEL CALCULATION" /> calculated by the engine</span>
        <span><SourceBadge type="USER INPUT" /> typed in by you</span>
        <span><SourceBadge type="MODEL ASSUMPTION" /> a modelling choice</span>
      </div>
    </div>
  );
}
