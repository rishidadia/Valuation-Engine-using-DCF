import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../services/api";

const FLOW = ["DATA", "ASSUMPTIONS", "FORECAST", "WACC", "DCF", "SENSITIVITY", "REPORT"];

export default function Landing() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<string>("checking…");

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth(`connected · ${h.database} database`))
      .catch(() => setHealth("backend not running — start it on port 8000"));
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-line">
        <div className="mx-auto max-w-[1100px] px-6 py-3 flex items-center justify-between">
          <span className="micro">dcf·labs</span>
          <span className="num text-[11px] text-dim">{health}</span>
        </div>
      </header>

      <main className="flex-1 flex items-center">
        <div className="mx-auto max-w-[1100px] px-6 py-16 w-full">
          <div className="max-w-3xl">
            <div className="micro mb-4 animate-fade-in">What is this company really worth?</div>
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight text-white animate-slide-up">
              DCF<span className="text-accent">·</span>LABS
            </h1>
            <p
              className="mt-3 text-[15px] leading-relaxed text-muted animate-slide-up"
              style={{ animationDelay: "0.08s" }}
            >
              A valuation tool for finance people. Give it your own company's numbers or a
              stock ticker, and it works out what the business is worth — then shows you
              every step, every assumption, and where each figure came from.
            </p>

            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              <button
                onClick={() => navigate("/workspace/data?mode=upload")}
                className="group panel px-6 py-5 text-left transition-all duration-200 hover:border-accent-dim/60 hover:-translate-y-0.5 animate-slide-up"
                style={{ animationDelay: "0.15s" }}
              >
                <div className="micro text-accent">Mode A</div>
                <div className="mt-2 text-[16px] text-white tracking-wide">VALUE MY COMPANY</div>
                <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                  Have your own financial statements? Upload them as an Excel file.
                  We'll read the sheets, show you exactly what we found, and flag
                  anything that's missing so you can fill it in.
                </p>
                <div className="mt-3 text-[11px] text-dim group-hover:text-accent transition-colors">
                  Excel upload · free template included →
                </div>
              </button>

              <button
                onClick={() => navigate("/workspace/data?mode=public")}
                className="group panel px-6 py-5 text-left transition-all duration-200 hover:border-accent-dim/60 hover:-translate-y-0.5 animate-slide-up"
                style={{ animationDelay: "0.22s" }}
              >
                <div className="micro text-accent">Mode B</div>
                <div className="mt-2 text-[16px] text-white tracking-wide">VALUE A PUBLIC COMPANY</div>
                <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                  Just type a stock ticker. We pull the company's official filings,
                  its current share price and today's interest rates — and label every
                  number with where it came from.
                </p>
                <div className="mt-3 text-[11px] text-dim group-hover:text-accent transition-colors">
                  Try AAPL · MSFT · NVDA · JPM →
                </div>
              </button>
            </div>

            <div
              className="mt-12 border-t border-line pt-6 animate-slide-up"
              style={{ animationDelay: "0.3s" }}
            >
              <div className="micro mb-3">How it works — seven simple steps</div>
              <div className="flex flex-wrap items-center gap-1.5">
                {FLOW.map((f, i) => (
                  <span key={f} className="flex items-center gap-1.5 animate-scale-in"
                        style={{ animationDelay: `${0.35 + i * 0.06}s` }}>
                    <span className="border border-line px-2 py-1 text-[10px] tracking-widest text-muted transition-colors hover:border-accent-dim/60 hover:text-accent">
                      {f}
                    </span>
                    {i < FLOW.length - 1 && <span className="text-[9px] text-ink-600">→</span>}
                  </span>
                ))}
              </div>
              <p className="mt-4 text-[12.5px] leading-relaxed text-dim max-w-2xl">
                You stay in charge the whole way: check the data, adjust any assumption
                you like, and see how the answer changes. Nothing is hidden — every
                number is labelled as either a source, something you typed, a
                calculation, or a stated assumption. If we can't find a figure, we say
                so rather than making one up.
              </p>
            </div>
          </div>
        </div>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-[1100px] px-6 py-4 flex flex-wrap justify-between gap-2 text-[11px] text-dim">
          <span>Model-based and highly sensitive to assumptions. Not investment advice.</span>
          <span className="text-ink-600">
            Built with FastAPI · LangGraph · React — the finance math is plain Python, fully tested
          </span>
        </div>
      </footer>
    </div>
  );
}
