/** Workspace layout: header (company + audit status), workflow nav, agent rail. */
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import AgentActivity from "./AgentActivity";
import GlobalLoader from "./GlobalLoader";
import WorkflowNav from "./WorkflowNav";
import { AuditBadge, Notice } from "./ui";
import { ErrorBanner } from "./ui";
import { fmtMoney, fmtPct, fmtSigned } from "../lib/format";
import { useValuation } from "../state/ValuationContext";

export default function Layout() {
  const { view, error, notice, clearError, busy, reset } = useValuation();
  const navigate = useNavigate();
  const location = useLocation();
  const s = view?.summary;
  const company = view?.company ?? s?.company;

  return (
    <div className="min-h-screen">
      <GlobalLoader />
      <header className="border-b border-line bg-ink-900">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-4">
            <Link to="/" className="group flex items-baseline gap-2">
              <span className="text-[15px] font-semibold tracking-tight text-white group-hover:text-accent transition-colors">
                DCF<span className="text-accent">·</span>LABS
              </span>
              <span className="micro hidden sm:block">Computational Valuation Engine</span>
            </Link>
            {company && (
              <div className="hidden md:flex items-baseline gap-3 border-l border-line pl-4">
                <span className="text-[13px] text-[#dfe3ea]">{company.name}</span>
                {company.ticker && (
                  <span className="num text-[12px] text-muted">{company.ticker}</span>
                )}
                {s?.current_share_price != null && (
                  <span className="num text-[12px] text-muted">
                    {fmtMoney(s.current_share_price, "$", 2)}
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {busy && (
              <span className="inline-flex items-center gap-2 text-[11px] text-accent">
                <span className="h-2.5 w-2.5 animate-spin rounded-full border border-accent-dim border-t-transparent" />
                recomputing
              </span>
            )}
            {s && <AuditBadge status={s.audit_status} />}
            {s?.status === "blocked" && (
              <span className="border border-down/40 bg-down/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-down">
                blocked
              </span>
            )}
            <button
              className="btn-ghost !py-1 !px-2.5 !text-[10px]"
              onClick={() => {
                reset();
                navigate("/");
              }}
            >
              New valuation
            </button>
          </div>
        </div>
      </header>

      <WorkflowNav />

      <main className="mx-auto max-w-[1440px] px-4 py-5">
        {notice && <Notice text={notice} />}
        {error && <ErrorBanner message={error.message} hint={error.hint} onDismiss={clearError} />}
        {s?.status === "blocked" && s.blocked_reasons?.length > 0 && (
          <div className="mb-4 border border-down/40 bg-down/5 px-4 py-3">
            <div className="micro text-down">Valuation blocked by audit</div>
            <ul className="mt-1 space-y-0.5 text-[12px] text-[#f8d4d4]">
              {s.blocked_reasons.map((r, i) => (
                <li key={i}>• {r}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_320px]">
          <div className="min-w-0">
            {/* keyed by route so each page gently animates in */}
            <div key={location.pathname} className="animate-slide-up">
              <Outlet />
            </div>
          </div>
          <aside className="hidden xl:block">
            <div className="sticky top-24 space-y-4">
              {view && (view.agents?.length ?? 0) > 0 ? (
                <AgentActivity agents={view.agents} />
              ) : (
                <div className="panel px-4 py-3">
                  <div className="micro">Agent Activity</div>
                  <p className="mt-2 text-[12px] text-muted">
                    Run a valuation to see the 12-agent workflow report here.
                  </p>
                </div>
              )}
              {view && (
                <div className="panel px-4 py-3">
                  <div className="micro">Live summary</div>
                  <p className="mt-1.5 text-[11px] text-dim">
                    Model estimate vs market — always compared side by side.
                  </p>
                  <dl className="mt-2 space-y-1.5 text-[12px]">
                    <Row k="Market price (real)" v={fmtMoney(s?.current_share_price, "$", 2)} />
                    <Row k="Our estimate / share" v={fmtMoney(s?.implied_share_price, "$", 2)} />
                    <Row k="Difference vs market" v={fmtSigned(s?.upside_downside)} />
                    <Row k="WACC (discount rate)" v={fmtPct(s?.wacc)} />
                    <Row k="Terminal growth" v={fmtPct(s?.terminal_growth)} />
                    <Row k="Enterprise value" v={fmtMoney(s?.enterprise_value)} />
                    <Row k="Equity value" v={fmtMoney(s?.equity_value)} />
                    <Row k="FCF CAGR" v={fmtPct(s?.fcf_cagr, 1)} />
                  </dl>
                </div>
              )}
            </div>
          </aside>
        </div>
      </main>

      <footer className="mt-8 border-t border-line px-4 py-5">
        <div className="mx-auto max-w-[1440px] text-[11px] text-dim">
          DCF·LABS — model-based valuation. Every number is traceable to a source, a user input,
          a calculation or an explicit assumption. Not investment advice.
        </div>
      </footer>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-dim">{k}</dt>
      <dd className="num text-[#dfe3ea]">{v}</dd>
    </div>
  );
}
