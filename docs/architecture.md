# System Architecture

DCF labs is a two-service application: a **FastAPI + LangGraph backend** that owns all
data retrieval and financial mathematics, and a **React/TypeScript frontend** that is a
typed, stateful viewer over the backend's Pydantic contracts.

```
┌─────────────────────────────── Browser ───────────────────────────────┐
│  Landing → Data → Assumptions → Forecast → WACC → FCF → DCF →        │
│  Sensitivity → Scenarios → Comps → Audit → Report                    │
│  React 18 · React Router 6 · Recharts 2 · Tailwind 3                 │
│  ValuationContext persists valuation/company ids to localStorage     │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTP /api (Vite proxy → :8000)
┌───────────────────────────────▼───────────────────────────────────────┐
│                        FastAPI  (backend/app)                        │
│                                                                       │
│  main.py ─ lifespan: init_db() · CORS · AppError handler              │
│                                                                       │
│  api/          23 routes                                              │
│    routes_company.py    POST /company/public · /company/upload        │
│                          GET  /company/template · /company/{id}       │
│                          PATCH /company/{id}/metrics                  │
│    routes_valuation.py  POST /valuation/run · GET /valuation/{id}     │
│                          + /financials /forecast /wacc /fcf /dcf      │
│                            /sensitivity /comparables /report /audit   │
│                            /agents /sources · POST /assumptions       │
│                            /scenarios · GET /valuations               │
│                                                                       │
│  workflows/valuation_graph.py ─ LangGraph DAG (see below)            │
│  agents/      12 agents — research, data, validation, historical,     │
│               forecasting, wacc, fcf, dcf, sensitivity, comparables,  │
│               report, audit (each logs via agent_run context manager) │
│                                                                       │
│  services/    deterministic pipeline stages (pure logic, no I/O):     │
│               historical, assumptions, forecast, wacc, fcf, dcf,      │
│               sensitivity, scenarios, comparables, audit, report,     │
│               core (run_* helpers), engine (PipelineContext,          │
│               build_view/recompute_view, active_values for scenarios) │
│                                                                       │
│  valuation/   PURE math — no imports from services, DB or HTTP:       │
│               capm · wacc · fcf · dcf · beta · sensitivity            │
│                                                                       │
│  data/providers/  base (DataProvider ABC, HttpClient w/ retries)      │
│               sec.py (EDGAR XBRL) · yahoo.py (prices, OLS beta)       │
│               fred.py (DGS10) · excel.py (workbook ingestion)         │
│               public_company.py (composite + curated peers)           │
│               registry in __init__.py: register_provider/get_provider │
│                                                                       │
│  schemas/     Pydantic contracts shared with the frontend            │
│  models/orm + db/   SQLAlchemy 2.0 — 17 tables (SQLite by default)    │
│  core/        config (pydantic-settings) · errors (AppError tree)     │
│               llm.py (optional, narrative text only)                  │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
        SEC EDGAR · Yahoo Finance · FRED · uploaded .xlsx · SQLite/PG
```

## The workflow graph

`backend/app/workflows/valuation_graph.py` builds a linear LangGraph with one
conditional branch at the audit gate:

```
START → research → data → validation → historical → forecast → wacc → fcf
      → dcf → sensitivity → comparables → audit
      → (audit.can_finalize ? report : blocked_notice → report) → END
```

- Every node wraps an agent's `run()` with `agent_run(...)`, which records the agent's
  status, messages, warnings and duration into the `agent_runs` table — surfaced on the
  frontend as the live Agent Activity feed and the `/valuation/{id}/agents` endpoint.
- `blocked_notice` does **not** skip the report: the report is always produced, but the
  valuation's `summary.status` is `"blocked"` and finalization is refused.
- The graph is deterministic: agents call services; services call `valuation/` math;
  no LLM is required anywhere in the path.

## Data flow for a valuation run

1. **Ingest** — Mode B: `public_company` provider composites SEC (fundamentals), Yahoo
   (price history, beta regression) and FRED (risk-free) into a `CompanyView` with
   per-metric provenance. Mode A: `excel.py` parses the workbook with heuristic
   sheet/label/period detection, unit inheritance and cell provenance (`Sheet!rowN`).
2. **Persist** — company + metrics written via repository; `POST /valuation/run`
   creates a valuation row and executes the graph.
3. **Compute** — engine stages build forecast → WACC → FCF → DCF → sensitivity →
   comparables; every intermediate is stored so each page can fetch its own slice.
4. **Override & recompute** — `POST /assumptions` and `POST /scenarios` apply deltas
   through `apply_overrides` (bounds-validated) and `recompute_view`, re-running only
   the affected stages. Precedence: **USER OVERRIDE > user input > model estimate**.
5. **Audit** — 21 checks across 10 families, including independent recomputation of
   CAPM, WACC, discount factors, terminal value, EV and the equity bridge; a critical
   failure blocks finalization.
6. **Report** — typed sections rendered as Markdown or full JSON export.

## Frontend structure

- `src/services/api.ts` — typed fetch wrapper; `ApiError` carries the backend's error
  `code` and `hint` so failures render as actionable messages, not stack traces.
- `src/state/ValuationContext.tsx` — holds current company/valuation ids (persisted to
  localStorage), exposes `run`, `applyAssumptions`, `applyScenario`.
- `src/pages/*` — one page per workflow stage; `WorkflowNav` reflects stage status.
- `src/charts/*` — Recharts wrappers (history vs forecast, FCF bridge, tornado).
- `src/components/Heatmap.tsx` — sensitivity grid renderer.
- Percent inputs are edited as `8.00` and divided by 100 on apply, so the UI speaks
  percent while the API speaks decimals.

## Error handling

- Backend raises `AppError` subclasses (`TickerNotFoundError`, `ExcelValidationError`,
  `TerminalValueError`, `AuditBlockedError`…) with HTTP status + machine `code` +
  human `hint`, handled by one FastAPI exception handler.
- Provider HTTP calls go through `HttpClient` with bounded retries; failures degrade to
  a flagged missing metric (WARNING), never a fabricated value.

## Database

- SQLite (`backend/dcflabs.db`) by default; set `DATABASE_URL` to a Postgres URL to
  switch. `init_db()` runs on lifespan. 17 tables including companies, metrics,
  periods, valuations, agent_runs, assumptions, and per-stage result tables.
