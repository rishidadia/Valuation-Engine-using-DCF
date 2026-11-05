# Data Sources

DCF labs retrieves data from three public sources for Mode B (public ticker) and from
the user's workbook for Mode A. **No data point is ever fabricated**: anything that
cannot be retrieved is flagged as missing and surfaced for manual entry.

All provider calls go through `HttpClient` (`backend/app/data/providers/base.py`) with
bounded retries, timeouts and a proper `User-Agent`. Providers are registered in a
registry (`register_provider` / `get_provider`) and selected by source type.

## 1. SEC EDGAR — fundamentals (Mode B)

- **Endpoint**: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
  (plus `https://www.sec.gov/files/company_tickers.json` for ticker → CIK resolution
  and `data.sec.gov/submissions/CIK…` for filing metadata).
- **Requirement**: a descriptive `User-Agent` header with a real contact (SEC policy).
  Configurable via `SEC_USER_AGENT`; the default names the project maintainer.
- **Coverage**: last **8 fiscal years** of audited statements.
- **Metrics**: revenue, COGS, gross profit, operating expenses, EBIT (OperatingIncomeLoss),
  interest, EBT, tax expense, net income, D&A, operating cash flow, CapEx, cash,
  short/long-term debt, current assets/liabilities, AR, inventory, AP, total assets,
  total liabilities, shareholders' equity, shares outstanding
  (`dei:EntityCommonStockSharesOutstanding`).
- **Derived values**: EBITDA (EBIT + D&A) and total debt (short + long term) are
  computed from reported SEC values and labeled **MODEL CALCULATION**, with the
  derivation shown in the source column.
- Every metric records: concept name, period, fiscal year, source URL/reference and
  status (`Retrieved` / `Missing` / `User-edited`).

## 2. Yahoo Finance — price history and beta

- **Endpoint**: `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`
  (keyless chart API; range/interval query parameters).
- **Used for**:
  - Latest close (for upside/downside vs implied share price).
  - Daily price history for beta regression.
- **Beta is computed, not quoted**: our own **OLS regression** of the security's daily
  returns against **SPY** daily returns over **2 years**
  (`backend/app/valuation/beta.py`). The slope of the fit is β; R² and the sample size
  are reported alongside. This is deliberately not an opaque vendor beta field.
- Market equity for capital weights = latest close × shares outstanding.

## 3. FRED — risk-free rate

- **Endpoint**: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`
  (10-year Treasury constant-maturity rate, CSV, keyless).
- The latest observation becomes the default `R_f` (shown as PUBLIC API / Retrieved).
- A configured default (`default_risk_free_rate` in `core/config.py`) is only a
  labeled fallback and is always displayed as such.

**Note**: stooq.com is JS-challenged/blocked and is deliberately not used.

## 4. Mode A — uploaded workbook (Excel provider)

- `.xlsx` only, 10 MB limit (enforced by `core/config.py`).
- Heuristic ingestion (`data/providers/excel.py`):
  - sheet detection by name/role (income statement, cash flow, balance sheet,
    assumptions, debt schedule),
  - label matching against a synonym table (e.g. "Total Revenue", "Net Sales" → revenue),
  - period header detection (FY2020, 2020, Dec-2020 …),
  - **unit inheritance** (thousands/millions stated once applies to the block),
  - sign normalization (outflows stored consistently as outflows),
  - **cell-level provenance** — every value is traceable to `Sheet!rowN`.
- `GET /api/company/template` downloads a generated template workbook (README,
  Income Statement, Cash Flow, Balance Sheet, Assumptions, Debt Schedule) whose labels
  and headers the parser detects natively.

## 5. Curated peer universe (comparables)

- `public_company.py` carries a curated `SUGGESTED_PEERS` universe; on Mode B ingest the
  data agent suggests peers (e.g. AAPL → MSFT, GOOGL, META) as a visible warning so the
  user can edit the peer list on the Comparables page.
- A minimum of **2 valid peers** is required before multiples are shown.

## 6. Provider provenance on every value

Each metric returned to the frontend carries:

| Field | Example |
|---|---|
| source | `SEC EDGAR XBRL OperatingIncomeLoss` |
| source_type | `PUBLIC API` / `MODEL CALCULATION` / `USER INPUT` |
| period | `FY2025` |
| status | `Retrieved` / `Calculated` / `Missing` / `Edited` |

The Data Review page renders exactly this table before any valuation runs, and the
Audit page re-lists sources for the final report.

## 7. Degradation policy

- A failed or partial provider call never blocks ingest: the affected metrics are
  marked missing, listed under "Provider gaps" in the audit (WARNING), and flagged for
  manual entry in the UI.
- Missing revenue in the latest period is a **critical/audit FAIL** (nothing to value);
  missing shares is a WARNING that leaves `implied_share_price` null.
- Network errors surface with a machine code and a human hint via `ApiError`.

## 8. Currency and geographic coverage

- Mode A accepts optional `currency` (ISO 4217, e.g. `EUR`) and `fiscal_year_end`
  (`MM-DD`, e.g. `09-30`) form fields. A currency code found in the workbook header is
  used when the field is omitted; `USD` and 12-31 remain the defaults.
- The currency is a **reporting label only** — no FX conversion is applied. Market inputs
  (risk-free rate, beta benchmark) stay US-dollar based, so a non-USD workbook is flagged
  with an explicit warning and should have its beta, risk-free rate and MRP overridden.
- Mode B is US-only by construction: SEC EDGAR XBRL fundamentals, Yahoo prices regressed
  against SPY, and the FRED DGS10 10-year Treasury yield. Non-US tickers normally fail at
  the fundamentals step.
- The SEC requires a truthful contact in the request User-Agent. `SEC_USER_AGENT` defaults
  to the project maintainer; set it to your own contact for a deployment.
