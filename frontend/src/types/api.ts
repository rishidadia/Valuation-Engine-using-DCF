/** Types mirroring the FastAPI / Pydantic response schemas (snake_case JSON). */

export type SourceType =
  | "PUBLIC_API"
  | "UPLOADED_EXCEL"
  | "USER_INPUT"
  | "MODEL_CALCULATION"
  | "MODEL_ASSUMPTION"
  | "USER_OVERRIDE";

export type ValueStatus =
  | "Retrieved"
  | "Estimated"
  | "Calculated"
  | "Override"
  | "Missing"
  | "User Data";

export type CheckStatus = "PASS" | "WARNING" | "FAIL";

export interface SourcedValue {
  value: number | null;
  unit: string;
  currency?: string | null;
  period?: string | null;
  source_type: SourceType;
  source: string;
  source_url?: string | null;
  retrieved_at?: string | null;
  confidence?: number | null;
  is_user_override?: boolean;
  status: ValueStatus;
  note?: string | null;
  original_value?: number | null;
  original_unit?: string | null;
  cell_ref?: string | null;
}

export interface Assumption {
  key: string;
  label: string;
  group: string;
  value: number | null;
  unit: string;
  currency?: string | null;
  historical_value?: number | null;
  model_estimate?: number | null;
  user_value?: number | null;
  source_type: SourceType;
  source: string;
  source_url?: string | null;
  retrieved_at?: string | null;
  status: ValueStatus;
  editable: boolean;
  min_value?: number | null;
  max_value?: number | null;
  note?: string | null;
}

export interface SourceRecord {
  id: string;
  name: string;
  source_type: SourceType;
  url?: string | null;
  retrieved_at?: string | null;
  description?: string | null;
  metrics: string[];
}

export interface AgentRun {
  agent: string;
  key: string;
  status: "pending" | "running" | "success" | "warning" | "failed" | "skipped";
  action: string;
  result: string;
  warnings: string[];
  sources: string[];
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  llm_used: boolean;
}

export interface CompanyInfo {
  id?: string | null;
  name: string;
  ticker?: string | null;
  exchange?: string | null;
  cik?: string | null;
  currency: string;
  industry?: string | null;
  sector?: string | null;
  sic_code?: string | null;
  is_public: boolean;
  description?: string | null;
  source_type: SourceType;
  source: string;
  source_url?: string | null;
  retrieved_at?: string | null;
  provider?: string | null;
  notes: string[];
}

export interface PeriodData {
  period: string;
  fiscal_year: number;
  end_date?: string | null;
  period_type: string;
  is_forecast: boolean;
  currency: string;
  unit_scale: number;
  metrics: Record<string, SourcedValue>;
}

export interface DataReviewRow {
  key: string;
  field: string;
  value: number | null;
  display?: string | null;
  unit: string;
  currency?: string | null;
  period?: string | null;
  source: string;
  source_type: SourceType;
  status: ValueStatus;
  critical: boolean;
  note?: string | null;
  cell_ref?: string | null;
}

export interface DataReview {
  company: CompanyInfo;
  rows: DataReviewRow[];
  missing_critical: string[];
  warnings: string[];
  periods: string[];
}

export interface IngestResponse {
  company_id: string;
  mode: "public" | "excel";
  review: DataReview;
  warnings: string[];
  agents: AgentRun[];
}

export interface RatioRow {
  period: string;
  fiscal_year: number;
  values: Record<string, SourcedValue>;
}

export interface HistoricalAnalysis {
  periods: string[];
  rows: RatioRow[];
  summary: Record<string, SourcedValue>;
  facts: string[];
  interpretation: string[];
  proposed_assumptions: Assumption[];
}

export interface ForecastYear {
  period: string;
  year_index: number;
  revenue_growth: SourcedValue;
  revenue: SourcedValue;
  ebit_margin: SourcedValue;
  ebit: SourcedValue;
  da: SourcedValue;
  capex: SourcedValue;
  change_nwc: SourcedValue;
  ebitda: SourcedValue;
  driver_note: string;
}

export interface ForecastResult {
  method: string;
  years: ForecastYear[];
  start_period: string;
  assumptions_used: string[];
  notes: string[];
  alternative?: Record<string, unknown> | null;
}

export interface BetaDetail {
  ticker?: string | null;
  name?: string | null;
  levered_beta?: number | null;
  tax_rate?: number | null;
  debt_equity?: number | null;
  unlevered_beta?: number | null;
  selected: boolean;
  note?: string | null;
}

export interface WaccCalculation {
  market_value_equity: SourcedValue;
  market_value_debt: SourcedValue;
  equity_weight: SourcedValue;
  debt_weight: SourcedValue;
  risk_free_rate: SourcedValue;
  beta: SourcedValue;
  market_risk_premium: SourcedValue;
  cost_of_equity: SourcedValue;
  cost_of_debt: SourcedValue;
  after_tax_cost_of_debt: SourcedValue;
  tax_rate: SourcedValue;
  wacc: SourcedValue;
  capm_formula: string;
  wacc_formula: string;
  cost_of_equity_method: "capm" | "manual";
  beta_method: "market" | "comparables" | "manual";
  cost_of_debt_method: "interest_bearing" | "instruments" | "manual";
  tax_rate_method: "historical_effective" | "statutory" | "manual";
  capital_structure_method: "current" | "target" | "manual";
  beta_details: BetaDetail[];
  debt_instruments: Record<string, unknown>[];
  warnings: string[];
}

export interface FcfYear {
  period: string;
  year_index: number;
  revenue: SourcedValue;
  ebit: SourcedValue;
  tax_rate: SourcedValue;
  tax_expense: SourcedValue;
  nopat: SourcedValue;
  da: SourcedValue;
  capex: SourcedValue;
  change_nwc: SourcedValue;
  fcf: SourcedValue;
  discount_factor?: number | null;
  pv_fcf?: number | null;
  formula: string;
}

export interface FcfSchedule {
  years: FcfYear[];
  fcf_cagr?: number | null;
  margins: number[];
  notes: string[];
}

export interface TerminalMethodResult {
  method: "perpetuity_growth" | "exit_multiple";
  label: string;
  terminal_value?: number | null;
  pv_terminal_value?: number | null;
  formula: string;
  inputs: Record<string, number>;
  valid: boolean;
  issue?: string | null;
  ev?: number | null;
  equity_value?: number | null;
  implied_share_price?: number | null;
}

export interface DcfResult {
  discount_rate: number;
  forecast_years: number;
  pv_rows: { period: string; fcf: number; discount_factor: number; pv: number; index: number }[];
  pv_forecast_fcf: number;
  terminal_methods: TerminalMethodResult[];
  selected_method: "perpetuity_growth" | "exit_multiple";
  enterprise_value?: number | null;
  cash?: number | null;
  debt?: number | null;
  equity_value?: number | null;
  shares_outstanding?: number | null;
  implied_share_price?: number | null;
  current_share_price?: number | null;
  upside_downside?: number | null;
  terminal_growth?: number | null;
  exit_multiple?: number | null;
  fcf_cagr?: number | null;
  bridge: { label: string; value: number | null; detail: string }[];
  warnings: string[];
  valid: boolean;
  issue?: string | null;
}

export interface SensitivityTable {
  key: string;
  title: string;
  row_label: string;
  col_label: string;
  row_values: number[];
  col_values: number[];
  matrix: (number | null)[][];
  base_value?: number | null;
  base_row?: number | null;
  base_col?: number | null;
  unit: "price" | "ev" | "equity";
  note?: string | null;
}

export interface TornadoItem {
  input_key: string;
  label: string;
  low: number;
  high: number;
  low_result?: number | null;
  high_result?: number | null;
  base_result?: number | null;
  swing?: number | null;
  note?: string | null;
}

export interface SensitivityResult {
  tables: SensitivityTable[];
  tornado: TornadoItem[];
  base_implied_price?: number | null;
  notes: string[];
}

export interface ScenarioResult {
  name: string;
  label: string;
  overrides: Record<string, number>;
  wacc?: number | null;
  terminal_growth?: number | null;
  enterprise_value?: number | null;
  equity_value?: number | null;
  implied_share_price?: number | null;
  upside_downside?: number | null;
  valid: boolean;
  issue?: string | null;
}

export interface ScenarioComparison {
  active: string;
  scenarios: ScenarioResult[];
}

export interface PeerMetrics {
  ticker: string;
  name?: string | null;
  currency?: string | null;
  ev?: number | null;
  revenue?: number | null;
  ebitda?: number | null;
  ebit?: number | null;
  net_income?: number | null;
  market_cap?: number | null;
  ev_revenue?: number | null;
  ev_ebitda?: number | null;
  ev_ebit?: number | null;
  pe?: number | null;
  levered_beta?: number | null;
  source: string;
  source_url?: string | null;
  retrieved_at?: string | null;
  note?: string | null;
}

export interface ComparablesResult {
  status: "ok" | "insufficient_data";
  peers: PeerMetrics[];
  multiple_stats: Record<string, { median?: number | null; mean?: number | null; count: number }>;
  implied_values: {
    multiple: string;
    peer_median: number;
    subject_metric: number;
    implied_ev?: number | null;
    implied_equity?: number | null;
    implied_price?: number | null;
    vs_dcf?: number | null;
  }[];
  subject_metrics: Record<string, number | null>;
  notes: string[];
  dcf_vs_comps?: {
    dcf_price: number;
    comps_median_price: number;
    spread: number;
    commentary: string;
  } | null;
}

export interface Check {
  name: string;
  status: CheckStatus;
  detail: string;
  severity: "info" | "warning" | "critical";
  related?: string | null;
}

export interface AuditResult {
  status: CheckStatus;
  checks: Check[];
  blocking_issues: string[];
  can_finalize: boolean;
}

export interface ReportSection {
  heading: string;
  kind: "FACT" | "CALCULATION" | "ASSUMPTION" | "USER OVERRIDE" | "MODEL ESTIMATE" | "NARRATIVE" | "WARNING";
  body: string;
  table?: { columns: string[]; rows: (string | number | null)[][] } | null;
}

export interface ReportDoc {
  title: string;
  subtitle: string;
  generated_at?: string | null;
  disclaimer: string;
  sections: ReportSection[];
  audit_status: CheckStatus;
  markdown: string;
  llm_used: boolean;
}

export interface ValuationSummary {
  id?: string | null;
  status: "complete" | "blocked" | "draft";
  company: CompanyInfo;
  created_at?: string | null;
  current_share_price?: number | null;
  implied_share_price?: number | null;
  upside_downside?: number | null;
  enterprise_value?: number | null;
  equity_value?: number | null;
  wacc?: number | null;
  terminal_growth?: number | null;
  fcf_cagr?: number | null;
  audit_status: CheckStatus;
  blocked_reasons: string[];
}

export interface ValuationView {
  summary: ValuationSummary;
  company: CompanyInfo;
  options?: ValuationOptions | null;
  historical_periods: PeriodData[];
  forecast?: ForecastResult | null;
  historical?: HistoricalAnalysis | null;
  assumptions: Assumption[];
  wacc?: WaccCalculation | null;
  fcf?: FcfSchedule | null;
  dcf?: DcfResult | null;
  sensitivity?: SensitivityResult | null;
  scenarios?: ScenarioComparison | null;
  comparables?: ComparablesResult | null;
  audit?: AuditResult | null;
  report?: ReportDoc | null;
  agents: AgentRun[];
  sources: SourceRecord[];
  errors: { code: string; detail: string; hint?: string }[];
}

export interface ValuationOptions {
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
