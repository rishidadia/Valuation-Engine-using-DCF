/**
 * Global loader — shown whenever the app is fetching data or running a
 * computation, so it never looks like the page froze. Rotating status lines
 * tell the user what stage the work is in.
 */
import { useEffect, useState } from "react";
import { useValuation } from "../state/ValuationContext";

const RUN_STEPS = [
  "Researching the company…",
  "Pulling financial statements…",
  "Validating every figure…",
  "Building the forecast…",
  "Computing WACC…",
  "Projecting free cash flow…",
  "Discounting to present value…",
  "Testing sensitivities…",
  "Running audit checks…",
  "Writing the report…",
];

const RECOMPUTE_STEPS = [
  "Recomputing valuation with your changes…",
  "Re-running forecast, WACC and DCF…",
  "Re-checking audit rules…",
];

export default function GlobalLoader() {
  const { busy, loading, notice } = useValuation();
  const [step, setStep] = useState(0);
  const active = busy || loading;

  const steps = notice?.includes("agent") ? RUN_STEPS : RECOMPUTE_STEPS;

  useEffect(() => {
    if (!active) {
      setStep(0);
      return;
    }
    const id = window.setInterval(() => {
      setStep((s) => (s + 1) % steps.length);
    }, 1400);
    return () => window.clearInterval(id);
  }, [active, steps.length]);

  if (!active) return null;

  return (
    <div
      data-testid="global-loader"
      className="fixed inset-0 z-[80] flex items-center justify-center bg-ink-950/80 backdrop-blur-[2px] animate-fade-in"
      role="status"
      aria-live="polite"
    >
      <div className="panel w-[340px] px-6 py-6 text-center">
        {/* animated ring */}
        <div className="mx-auto h-10 w-10 relative">
          <span className="absolute inset-0 rounded-full border-2 border-accent-dim/30" />
          <span className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-accent" />
          <span
            className="absolute inset-2 rounded-full border border-transparent border-b-accent/60 animate-spin"
            style={{ animationDirection: "reverse", animationDuration: "0.9s" }}
          />
        </div>
        <div className="mt-4 text-[13px] text-white">
          {notice && notice.includes("agent") ? "Running the valuation" : "Recomputing"}
        </div>
        <div className="mt-1 h-4 text-[11.5px] text-muted animate-fade-in" key={step}>
          {steps[step]}
        </div>
        {/* indeterminate progress bar */}
        <div className="mt-4 h-1 w-full overflow-hidden bg-ink-800">
          <div
            className="h-full w-1/3 bg-accent"
            style={{ animation: "loaderSlide 1.2s ease-in-out infinite" }}
          />
        </div>
        <div className="mt-3 text-[10.5px] text-dim">
          This can take a few seconds on a live fetch.
        </div>
      </div>
    </div>
  );
}
