/** ASSUMPTIONS & OVERRIDES — every model input with provenance + method selectors. */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ContextLabel, FormulaBox, Labeled, Radio, SectionHeader, SourceBadge, StatusText,
} from "../components/ui";
import { fmtMoney, fmtNum, fmtPct, fmtValue, tipFor } from "../lib/format";
import type { Assumption, ValuationOptions } from "../types/api";
import { useValuation } from "../state/ValuationContext";

const GROUPS: { key: string; title: string; blurb: string }[] = [
  { key: "forecast", title: "Forecast drivers", blurb: "Drive the 5-year projection." },
  { key: "wacc", title: "WACC inputs", blurb: "CAPM, capital structure, cost of debt, tax." },
  { key: "terminal", title: "Terminal value", blurb: "Perpetuity growth / exit multiple." },
  { key: "general", title: "General", blurb: "Forecast horizon, share data." },
];

const DEFAULT_OPTIONS: ValuationOptions = {
  cost_of_equity_method: "capm",
  beta_method: "market",
  cost_of_debt_method: "interest_bearing",
  tax_rate_method: "historical_effective",
  capital_structure_method: "current",
  terminal_method: "perpetuity_growth",
  beta_aggregation: "median",
  discount_convention: "end",
  forecast_years: 5,
  peer_tickers: [],
  run_comparables: true,
  run_sensitivity: true,
};

export default function AssumptionsPage() {
  const { view, applyAssumptions, busy } = useValuation();
  const navigate = useNavigate();
  const assumptions = view?.assumptions ?? [];
  const wacc = view?.wacc;
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [cleared, setCleared] = useState<string[]>([]);
  const [options, setOptions] = useState<ValuationOptions>(view?.options ?? DEFAULT_OPTIONS);

  useEffect(() => {
    if (view?.options) setOptions(view.options);
  }, [view?.options]);

  const byKey = useMemo(() => Object.fromEntries(assumptions.map((a) => [a.key, a])), [assumptions]);

  if (!view) {
    return <div className="panel px-4 py-6 text-[13px] text-muted">No valuation yet — start on the DATA page.</div>;
  }

  const dirty = Object.keys(edits).length > 0 || cleared.length > 0;

  const apply = async () => {
    const overrides: Record<string, number> = {};
    for (const [k, v] of Object.entries(edits)) {
      if (v.trim() === "") continue;
      let n = Number(v);
      if (Number.isNaN(n)) continue;
      // percent fields are edited as 8.00 but stored as 0.08
      if (byKey[k]?.unit === "percent") n = n / 100;
      overrides[k] = n;
    }
    await applyAssumptions(overrides, cleared, options as unknown as Record<string, unknown>);
    setEdits({});
    setCleared([]);
  };

  const setOpt = <K extends keyof ValuationOptions>(k: K, v: ValuationOptions[K]) =>
    setOptions((o) => ({ ...o, [k]: v }));

  const preview = capmPreview(byKey, options);

  return (
    <div>
      <SectionHeader
        title="Assumptions & Overrides"
        subtitle="Every input behind the valuation. If you change one, your version always wins — and stays clearly marked."
        right={
          <>
            <button
              className="btn-ghost"
              disabled={!dirty || busy}
              onClick={async () => {
                await applyAssumptions({}, Object.keys(edits).concat(cleared), options as unknown as Record<string, unknown>);
                setEdits({}); setCleared([]);
              }}
            >
              Revert edited
            </button>
            <button className="btn-primary" disabled={busy || (!dirty && !optionsChanged(view.options, options))}
                    onClick={apply}>
              {busy ? "Recomputing…" : dirty ? `Apply ${Object.keys(edits).length + cleared.length} change(s)` : "Apply method changes"}
            </button>
          </>
        }
      />

      <ContextLabel
        items={[
          { k: "Whose inputs", v: view?.company ? `the assumptions driving ${view.company.name}'s valuation` : "the assumptions driving this valuation" },
          { k: "Who wins", v: "your override → your data → model estimate (always in that order)" },
          { k: "What happens", v: "changes here re-run WACC, cash flows, DCF, sensitivity and the report" },
        ]}
      />

      {/* ---- method selectors ---- */}
      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <div className="panel px-4 py-3.5">
          <div className="micro mb-3">Cost of Equity method</div>
          <Radio
            name="coe"
            options={[{ value: "capm", label: "CAPM" }, { value: "manual", label: "Manual expected return" }]}
            value={options.cost_of_equity_method}
            onChange={(v) => setOpt("cost_of_equity_method", v as ValuationOptions["cost_of_equity_method"])}
          />
          {options.cost_of_equity_method === "capm" ? (
            <div className="mt-3 grid grid-cols-3 gap-2">
              <NumField label="Risk-Free Rate" a={byKey.risk_free_rate} edits={edits} setEdits={setEdits} pct />
              <NumField label="Beta" a={byKey.beta} edits={edits} setEdits={setEdits} />
              <NumField label="Market Risk Prem." a={byKey.market_risk_premium} edits={edits} setEdits={setEdits} pct />
            </div>
          ) : (
            <div className="mt-3 grid grid-cols-1 gap-2">
              <NumField label="Expected Cost of Equity" a={byKey.cost_of_equity} edits={edits} setEdits={setEdits} pct />
            </div>
          )}
          <div className="mt-3 space-y-2">
            <FormulaBox
              text={preview.capmText}
              result={`= ${fmtPct(preview.capm)}`}
            />
            {options.cost_of_equity_method === "manual" && (
              <FormulaBox
                text={`CAPM reference = ${fmtPct(preview.capm)}  |  User override = ${fmtPct(preview.manual)}  →  Used in WACC = ${fmtPct(preview.manual)}`}
                result="USER ASSUMPTION"
              />
            )}
          </div>
        </div>

        <div className="panel px-4 py-3.5">
          <div className="micro mb-3">Beta</div>
          <Radio
            name="beta"
            options={[
              { value: "market", label: "API / Market Beta" },
              { value: "comparables", label: "Comparable Companies" },
              { value: "manual", label: "Manual Beta" },
            ]}
            value={options.beta_method}
            onChange={(v) => setOpt("beta_method", v as ValuationOptions["beta_method"])}
          />
          {options.beta_method === "manual" && (
            <div className="mt-3 max-w-[200px]">
              <NumField label="Beta" a={byKey.beta} edits={edits} setEdits={setEdits} />
            </div>
          )}
          {options.beta_method === "comparables" && (
            <div className="mt-3">
              <Radio
                name="betaAgg"
                options={[{ value: "median", label: "Median unlevered" }, { value: "mean", label: "Mean unlevered" }]}
                value={options.beta_aggregation}
                onChange={(v) => setOpt("beta_aggregation", v as ValuationOptions["beta_aggregation"])}
              />
              {wacc && wacc.beta_details.length > 0 ? (
                <table className="mt-2 w-full text-left">
                  <thead>
                    <tr className="border-b border-line">
                      {["Peer", "Levered β", "D/E", "Unlevered β"].map((h) => (
                        <th key={h} className="micro py-1 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="num text-[12px]">
                    {wacc.beta_details.map((d) => (
                      <tr key={d.ticker} className="border-b border-line/60">
                        <td className="py-1 text-[#dfe3ea]">{d.ticker}</td>
                        <td className="py-1">{fmtNum(d.levered_beta)}</td>
                        <td className="py-1">{fmtNum(d.debt_equity)}</td>
                        <td className="py-1 text-accent">{fmtNum(d.unlevered_beta, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="mt-2 text-[11.5px] text-dim">
                  No peer beta data loaded. Add peer tickers when running the valuation, or switch to manual.
                </p>
              )}
              <p className="mt-2 text-[11px] text-dim">
                β<sub>U</sub> = β<sub>L</sub> / [1 + (1−T)(D/E)] → aggregate → relever at target D/E.
              </p>
            </div>
          )}
          {options.beta_method === "market" && wacc?.beta && (
            <div className="mt-3 text-[11.5px] text-muted">
              <FormulaBox text={wacc.beta.source ?? "market beta"} result={`β = ${fmtNum(wacc.beta.value)}`} />
              {wacc.beta.note && <p className="mt-1.5 text-dim">{wacc.beta.note}</p>}
            </div>
          )}
        </div>

        <div className="panel px-4 py-3.5">
          <div className="micro mb-3">Cost of Debt</div>
          <Radio
            name="cod"
            options={[
              { value: "interest_bearing", label: "Company borrowing rate" },
              { value: "instruments", label: "Debt instruments" },
              { value: "manual", label: "Manual" },
            ]}
            value={options.cost_of_debt_method}
            onChange={(v) => setOpt("cost_of_debt_method", v as ValuationOptions["cost_of_debt_method"])}
          />
          {options.cost_of_debt_method === "manual" ? (
            <div className="mt-3 max-w-[200px]">
              <NumField label="Cost of Debt" a={byKey.cost_of_debt} edits={edits} setEdits={setEdits} pct />
            </div>
          ) : options.cost_of_debt_method === "instruments" && wacc?.debt_instruments?.length ? (
            <table className="mt-3 w-full text-left">
              <thead>
                <tr className="border-b border-line">
                  {["Instrument", "Amount", "Rate"].map((h) => <th key={h} className="micro py-1 font-normal">{h}</th>)}
                </tr>
              </thead>
              <tbody className="num text-[12px]">
                {wacc.debt_instruments.map((d, i) => (
                  <tr key={i} className="border-b border-line/60">
                    <td className="py-1">{String(d.name ?? `Debt ${i + 1}`)}</td>
                    <td className="py-1">{fmtMoney(Number(d.amount ?? 0))}</td>
                    <td className="py-1">{fmtPct(Number(d.rate ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="mt-3 max-w-[200px]">
              <NumField label="Cost of Debt (derived)" a={byKey.cost_of_debt} edits={edits} setEdits={setEdits} pct />
            </div>
          )}
          {byKey.cost_of_debt?.note && <p className="mt-2 text-[11px] text-dim">{byKey.cost_of_debt.note}</p>}
        </div>

        <div className="panel px-4 py-3.5">
          <div className="micro mb-3">Tax rate & Capital structure</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="text-[11px] text-muted mb-1.5">Tax rate method</div>
              <Radio
                name="tax"
                options={[
                  { value: "historical_effective", label: "Historical effective" },
                  { value: "statutory", label: "Statutory" },
                  { value: "manual", label: "Manual" },
                ]}
                value={options.tax_rate_method}
                onChange={(v) => setOpt("tax_rate_method", v as ValuationOptions["tax_rate_method"])}
              />
              <div className="mt-2 max-w-[180px]">
                <NumField label="Tax Rate" a={byKey.tax_rate} edits={edits} setEdits={setEdits} pct />
              </div>
            </div>
            <div>
              <div className="text-[11px] text-muted mb-1.5">Capital structure</div>
              <Radio
                name="cap"
                options={[
                  { value: "current", label: "Current" },
                  { value: "target", label: "Target" },
                  { value: "manual", label: "Manual" },
                ]}
                value={options.capital_structure_method}
                onChange={(v) => setOpt("capital_structure_method", v as ValuationOptions["capital_structure_method"])}
              />
              {options.capital_structure_method === "target" && (
                <div className="mt-2 max-w-[180px]">
                  <NumField label="Target D/E" a={byKey.target_de} edits={edits} setEdits={setEdits} />
                </div>
              )}
              {options.capital_structure_method === "manual" && (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <NumField label="Equity weight" a={byKey.equity_weight} edits={edits} setEdits={setEdits} pct />
                  <NumField label="Debt weight" a={byKey.debt_weight} edits={edits} setEdits={setEdits} pct />
                </div>
              )}
            </div>
          </div>
          {wacc && (
            <div className="mt-3">
              <FormulaBox text={wacc.wacc_formula} result={`WACC = ${fmtPct(wacc.wacc.value)}`} />
            </div>
          )}
        </div>
      </div>

      {/* ---- assumption table ---- */}
      {GROUPS.map((g) => {
        const items = assumptions.filter((a) => a.group === g.key);
        if (!items.length) return null;
        return (
          <div key={g.key} className="mb-5">
            <div className="mb-2 flex items-baseline gap-3">
              <h2 className="text-[13px] uppercase tracking-widest text-muted">{g.title}</h2>
              <span className="text-[11px] text-dim">{g.blurb}</span>
            </div>
            <div className="panel overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-line">
                    {["Input", "Value", "Historical", "Model estimate", "User override", "Source", "Type", "Status", ""].map((h) => (
                      <th key={h} className="micro px-3 py-2 font-normal">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {items.map((a) => (
                    <AssumptionRow
                      key={a.key}
                      a={a}
                      edit={edits[a.key]}
                      onEdit={(v) => setEdits((e) => ({ ...e, [a.key]: v }))}
                      onRevert={() => {
                        setEdits((e) => { const n = { ...e }; delete n[a.key]; return n; });
                        if (a.user_value != null && !cleared.includes(a.key)) setCleared((c) => [...c, a.key]);
                      }}
                      pct={a.unit === "percent"}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      <div className="sticky bottom-3 z-30 mt-4 flex items-center justify-between border border-line bg-ink-900/95 px-4 py-2.5 backdrop-blur">
        <span className="text-[11.5px] text-dim">
          {dirty
            ? `${Object.keys(edits).length} edit(s), ${cleared.length} revert(s) pending — apply to recompute valuation.`
            : "All changes apply instantly to forecast, WACC, FCF, DCF, sensitivity and scenarios."}
        </span>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => navigate("/workspace/forecast")}>Forecast →</button>
          <button className="btn-primary" disabled={busy || (!dirty && !optionsChanged(view.options, options))} onClick={apply}>
            {busy ? "Recomputing…" : "Apply"}
          </button>
        </div>
      </div>
    </div>
  );
}

function optionsChanged(a?: ValuationOptions | null, b?: ValuationOptions): boolean {
  if (!a || !b) return false;
  return (Object.keys(b) as (keyof ValuationOptions)[]).some((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
}

function NumField({
  label, a, edits, setEdits, pct,
}: {
  label: string;
  a?: Assumption;
  edits: Record<string, string>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  pct?: boolean;
}) {
  const raw = edits[a?.key ?? label];
  const shown = raw ?? (a?.value != null ? (pct ? (a.value * 100).toFixed(2) : String(a.value)) : "");
  return (
    <Labeled label={label}>
      <div className="flex items-center gap-1">
        <input
          className="input !py-1"
          value={shown}
          disabled={!a?.editable}
          onChange={(e) => setEdits((ed) => ({ ...ed, [a!.key]: e.target.value }))}
        />
        {pct && <span className="text-[11px] text-dim">%</span>}
      </div>
      {a && (
        <div className="mt-0.5 flex items-center gap-1.5">
          <SourceBadge type={edits[a.key] != null ? "USER_OVERRIDE" : a.source_type} />
          <StatusText status={edits[a.key] != null ? "Override" : a.status} />
        </div>
      )}
    </Labeled>
  );
}

function AssumptionRow({
  a, edit, onEdit, onRevert, pct,
}: {
  a: Assumption;
  edit?: string;
  onEdit: (v: string) => void;
  onRevert: () => void;
  pct: boolean;
}) {
  const fmt = (v: number | null | undefined) => (v == null ? "—" : pct ? fmtPct(v) : fmtValue(v, a.unit, a.currency));
  const display = edit ?? (a.value == null ? "" : pct ? (a.value * 100).toFixed(2) : String(a.value));
  return (
    <tr className="row-hover">
      <td className="px-3 py-1.5 text-[12.5px] text-[#dfe3ea] whitespace-nowrap">
        <span
          className={a.source_type === "USER_OVERRIDE" || a.user_value != null ? "tip border-b border-orange-400/50" : ""}
          data-tip={tipFor(a)}
        >
          {a.label}
        </span>
      </td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1">
          <input
            className="input !py-0.5 !text-[12px] w-24 text-right"
            value={display}
            onChange={(e) => onEdit(e.target.value)}
          />
          {pct && <span className="text-[10px] text-dim">%</span>}
        </div>
      </td>
      <td className="num px-3 py-1.5 text-[12px] text-muted">{fmt(a.historical_value)}</td>
      <td className="num px-3 py-1.5 text-[12px] text-muted">{fmt(a.model_estimate)}</td>
      <td className={`num px-3 py-1.5 text-[12px] ${a.user_value != null ? "text-orange-300" : "text-dim"}`}>
        {fmt(a.user_value)}
      </td>
      <td className="px-3 py-1.5 text-[11.5px] text-muted max-w-[220px] truncate" title={a.source}>{a.source}</td>
      <td className="px-3 py-1.5"><SourceBadge type={a.source_type} /></td>
      <td className="px-3 py-1.5"><StatusText status={a.status} /></td>
      <td className="px-3 py-1.5 text-right whitespace-nowrap">
        {a.user_value != null && (
          <button className="text-[11px] text-dim hover:text-accent mr-2" onClick={onRevert}>revert</button>
        )}
        <span className="text-[10px] text-dim" title={a.note ?? ""}>ⓘ</span>
      </td>
    </tr>
  );
}

function capmPreview(byKey: Record<string, Assumption | undefined>, options: ValuationOptions) {
  const rf = byKey.risk_free_rate?.value ?? 0;
  const beta = byKey.beta?.value ?? 1;
  const mrp = byKey.market_risk_premium?.value ?? 0.05;
  const capm = rf + beta * mrp;
  const manualRaw = options.cost_of_equity_method === "manual" ? byKey.cost_of_equity : undefined;
  const manual = manualRaw?.value ?? capm;
  return {
    capm,
    manual,
    capmText: `Re = Rf + Beta × MRP = ${fmtPct(rf)} + (${fmtNum(beta, 2)} × ${fmtPct(mrp)})`,
  };
}
