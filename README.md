# DCF labs — Agentic DCF Valuation & Financial Analysis Platform

A production-quality computational-finance web application: value a company from either an
uploaded Excel workbook (**Mode A**) or a public ticker (**Mode B**) through a full
12-agent workflow — research → data → validation → historical analysis → forecast → WACC →
FCF → DCF → sensitivity → comparables → audit → report.

**Every important number is traceable** to one of exactly four things:

1. a **source** (SEC EDGAR, Yahoo Finance, FRED, an uploaded cell),
2. a **user input** (override),
3. a **calculation** (pure Python finance math), or
4. an **explicit model assumption**.

The system never fabricates financial data. Missing metrics are flagged for manual entry,
not guessed. Python owns all financial mathematics; agents handle research, extraction,
validation, orchestration and explanation only. An optional LLM (OpenAI / Groq / Google)
writes narrative text only — the pipeline is fully deterministic without it.

> Model-based and highly sensitive to assumptions. Not investment advice.

---

## Quick start

Two terminals are required (backend API + frontend dev server).

### Terminal 1 — Backend (FastAPI, port 8000)

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify: `curl http://127.0.0.1:8000/api/health` → `{"status":"ok",...}`

### Terminal 2 — Frontend (Vite + React, port 5173)

```bash
cd frontend
npm install        # first time only
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to `localhost:8000`, so the backend
must be running for Fetch / Run Valuation to work.

### Windows / PowerShell note

If the port is already in use by a previous run:

```bash
netstat -ano | findstr :8000        # find PID
taskkill /PID <pid> /F
```

---

## Project layout

```
dcfproject/
├── README.md
├── docs/
│   ├── architecture.md            # system design, workflow graph, data flow
│   ├── valuation_methodology.md   # CAPM, WACC, FCF, DCF, sensitivity — formulas
│   ├── data_sources.md            # SEC EDGAR, Yahoo, FRED, Excel ingestion
│   └── excel_template.md          # Mode A workbook format
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app, CORS, lifespan, error handler
│   │   ├── api/                   # 23 routes: company, valuation, template
│   │   ├── agents/                # 12 LangGraph agents (research…audit)
│   │   ├── workflows/             # valuation_graph.py — the agent DAG
│   │   ├── valuation/             # PURE math: capm, wacc, fcf, dcf, beta, sensitivity
│   │   ├── services/              # pipeline: historical, assumptions, forecast,
│   │   │                          #   wacc, fcf, dcf, audit, report, scenarios…
│   │   ├── data/providers/        # sec.py, yahoo.py, fred.py, excel.py, public_company.py
│   │   ├── schemas/               # Pydantic contracts shared with the frontend
│   │   ├── models/                # SQLAlchemy ORM (17 tables)
│   │   ├── db/                    # session + repository (SQLite by default)
│   │   └── core/                  # config, errors, optional LLM client
│   ├── tests/                     # 78 pytest tests (math, ingestion, API, audit)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── pages/                 # Landing, Data, Assumptions, Forecast, Wacc, Fcf,
    │   │                          #   Dcf, Sensitivity, Scenarios, Comparables, Audit, Report
    │   ├── components/            # ui, Layout, WorkflowNav, AgentActivity, Heatmap
    │   ├── charts/                # HistoryForecast, Fcf, Tornado (Recharts)
    │   ├── state/                 # ValuationContext (ids persisted to localStorage)
    │   ├── services/api.ts        # typed client, ApiError with code + hint
    │   └── types/api.ts           # mirrors backend Pydantic schemas
    └── vite.config.ts             # /api proxy → localhost:8000
```

---

## The workflow

| Stage | What happens | Page |
|---|---|---|
| 1. Data | Mode A: upload `.xlsx` (heuristic sheet/label/period detection, cell-level provenance `Sheet!rowN`). Mode B: ticker → SEC EDGAR fundamentals (last 8 FYs), Yahoo price + OLS beta vs SPY, FRED DGS10 risk-free. | Data Review |
| 2. Assumptions | CAPM or manual cost of equity; beta from market regression, comparables or manual; tax, cost of debt, capital structure. Precedence: **USER OVERRIDE > user input > model estimate**. | Assumptions |
| 3. Forecast | Driver-based 5-year forecast from historical relationships + assumptions. | Forecast |
| 4. WACC | R_e = R_f + β·MRP; after-tax cost of debt; weights; live sliders recompute client-side with the same identities. | WACC |
| 5. FCF | NOPAT + D&A − CapEx − ΔNWC per year, expandable walk per year. | FCF |
| 6. DCF | Both terminal methods always shown: perpetuity (invalid + explicit issue when WACC ≤ g) and exit multiple. Full equity bridge → implied share price. | DCF |
| 7. Sensitivity | WACC × g and WACC × exit-multiple heatmaps; tornado of top drivers. | Sensitivity |
| 8. Scenarios | Base / Bull / Bear / custom deltas applied as overrides, recomputed through the same engine. | Scenarios |
| 9. Comparables | Peer multiples (MIN_PEERS = 2) from a curated universe or user tickers. | Comps |
| 10. Audit | 21 checks across 10 families, including independent recomputation of CAPM, WACC, discount factors, TV, EV and the equity bridge; **critical failures block finalization** (`status: blocked`). | Audit |
| 11. Report | Typed sections, source tables, export as Markdown or full JSON. | Report |

### Contract highlights (spec-critical)

- **WACC ≤ terminal growth** → perpetuity method marked invalid with an explicit issue; the
  DCF falls back to `exit_multiple` with an explicit "unavailable" warning — never
  silently — and the audit still **FAILS / blocks** finalization.
- **Missing shares** → `implied_share_price` stays `null` (never fabricated) while equity
  value is still computed.
- **Percent fields** are edited as `8.00` in the UI and stored as `0.08`.
- Beta is **our own OLS regression** of daily returns vs SPY (2 years), not a vendor field.

---

## Data sources (all keyless, network-verified)

| Source | Used for | Notes |
|---|---|---|
| SEC EDGAR (`data.sec.gov` XBRL companyfacts) | Fundamentals, last 8 FYs, shares | Requires a `User-Agent` header |
| Yahoo Finance chart API | Price history, OLS beta vs SPY | `query1.finance.yahoo.com/v8/finance/chart` |
| FRED DGS10 CSV | 10-year risk-free rate | `fredgraph.csv?id=DGS10` |
| Uploaded workbook (Mode A) | Everything | `.xlsx` only, 10 MB limit, downloadable template |

stooq.com is JS-challenged/blocked and is deliberately not used.

---

## Tests

```bash
cd backend
python -m pytest tests/        # 125 passed
```

Covers: pure formula unit tests (CAPM, WACC, FCF, TV, sensitivity, beta), Excel
ingestion heuristics and percentage normalisation, date-aligned beta regression,
independent audit recomputation, manual cost of equity without beta, forecast
trajectories, API-key isolation, and API integration including a live AAPL flow,
audit gating and error contracts.

Frontend checks:

```bash
cd frontend
npx tsc --noEmit    # type check
npm run build       # production build
```

## Database

Defaults to SQLite (`backend/dcf_labs.db`) via `DATABASE_URL`; set a Postgres URL to
switch (SQLAlchemy 2.0). No external database is required to run locally.

---

## Upload options (Mode A)

`POST /api/company/upload` accepts two optional form fields alongside the workbook:

| Field | Example | Effect |
|---|---|---|
| `currency` | `EUR` | Reporting currency for every period. If omitted, an ISO code in the workbook header is used, else `USD`. |
| `fiscal_year_end` | `09-30` | Month/day used for each period's `end_date`. Defaults to 12-31. |

A non-USD currency is accepted and labelled, but it is **not converted**: market inputs
remain US-dollar based (see the coverage note below).

---

## Security & deployment

Local development is unauthenticated by default. For any shared or public deployment,
set a comma-separated allow list:

```bash
DCF_API_KEYS="key-one,key-two" python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

With keys configured:

- every `/api` route except `/api/health` and the blank Excel template requires an
  `X-API-Key` header (401 otherwise);
- each key is its own tenant: it can only read the companies and valuations it created
  (cross-tenant access returns 404, so existence is not leaked);
- ownership is stored as a truncated SHA-256 tenant id in the company's metadata — the
  key itself is never persisted, and no schema migration is required;
- the frontend sends the key from `localStorage["dcf_api_key"]` when present.

Also before exposing the API: restrict `CORS_ORIGINS`, terminate TLS in front of
uvicorn, and back up the database. The SEC requires a real contact in the User-Agent;
`SEC_USER_AGENT` defaults to the project maintainer and should be set per deployment.

---

## Scope and limitations

- **Geography:** fundamentals come from SEC EDGAR and market inputs from Yahoo/SPY and
  FRED DGS10, so the engine is a US-company valuation tool. Non-US tickers will usually
  fail at the fundamentals step.
- **Currency:** the workbook currency is a reporting label, not an FX conversion. A EUR
  workbook is valued with US market inputs unless you override beta, the risk-free rate
  and the risk premium explicitly.
- **Forecasting:** the model is deterministic and driver-based. Optional trajectories
  (`growth_path`, `ebit_margin_path`, `growth_fade_to_terminal`,
  `margin_convergence_years` on the run options) allow non-constant growth and margin
  paths; there is no ML forecaster.
