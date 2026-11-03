# Valuation Methodology

All formulas below are implemented as **pure functions** in `backend/app/valuation/`
and unit-tested. They depend only on Python numerics (no I/O, no framework), which is
what makes the system auditable: the same function is exercised by tests, by the
pipeline, and by client-side identity widgets in the UI.

Rates are stored as **decimals** (`0.08` = 8%). The UI edits percent (`8.00`) and
divides by 100 on apply.

## 1. CAPM — cost of equity

```
R_e = R_f + β × MRP
```

- `R_f` — risk-free rate, from FRED DGS10 (10-year Treasury constant maturity) or a
  user override.
- `β` — one of three selectable sources, always shown:
  1. **Market regression** (default for Mode B): our own OLS regression of daily
     returns against SPY over 2 years — not a vendor-supplied opaque field.
  2. **Comparable companies**: relevered from peer unlevered betas.
  3. **Manual input**.
- `MRP` — equity risk premium, a model assumption (explicitly labeled), overridable.

Alternative method: **manual expected return** (user supplies `R_e` directly).

## 2. Cost of debt

```
R_d(pre-tax)  = interest_expense / average_total_debt     (or user input)
R_d(after-tax) = R_d × (1 − t)
```

Tax rate `t` comes from the historical effective rate (tax expense / EBT), a model
assumption, or a user override. Audit enforces `0 ≤ t ≤ 50%`.

## 3. Capital weights

```
w_e = E / (D + E)        w_d = D / (D + E)        w_e + w_d = 1
```

`E` is market equity (price × shares) when available, else book equity as an explicit
model estimate. `D` is total debt — short + long term — counted **once** (audit checks
for double counting).

## 4. WACC

```
WACC = w_e × R_e + w_d × R_d(after-tax)
```

Audit enforces `0.5% ≤ WACC ≤ 30%` and `|w_e + w_d − 1| ≤ 1e-6`.

## 5. Unlevered / relevered beta (comparables path)

```
β_unlevered   = β_levered / (1 + (1 − t) × D/E)
β_relevered   = β_unlevered × (1 + (1 − t) × D/E_target)
```

## 6. Free cash flow

Per forecast year:

```
NOPAT = EBIT × (1 − t)
FCF   = NOPAT + D&A − CapEx − ΔNWC
```

- Tax is applied to EBIT (unlevered treatment) — audit verifies this.
- Drivers (revenue growth, EBIT margin, D&A % of revenue, CapEx % of revenue,
  ΔNWC % of revenue change) are forecast from historical relationships + assumptions,
  each individually overridable.
- The audit **recomputes every forecast year** from its drivers and fails (blocking) if
  stored FCF deviates from the formula beyond tolerance.

## 7. Terminal value — both methods always shown

**Perpetuity growth (Gordon):**

```
TV = FCF_n × (1 + g) / (WACC − g)
```

- Valid only when `WACC > g`. Otherwise the method is marked **invalid** with an
  explicit issue string — it is never silently computed with a negative denominator.
- If the perpetuity method is unavailable, the DCF falls back to the exit-multiple
  method **with an explicit "unavailable" warning** and the audit still fails/blocks
  finalization (`summary.status == "blocked"`).

**Exit multiple:**

```
TV = terminal EBITDA × exit_multiple
```

Both methods are discounted at WACC over the same 5-year horizon and displayed side
side with their PV, EV, implied price and `PV(TV) / EV` share. The audit warns when
terminal value exceeds 80% of EV.

## 8. Discounting and the equity bridge

```
PV(FCF) = Σ  FCF_t / (1 + WACC)^t          t = 1..5
EV      = Σ PV(FCF_t) + PV(TV)
Equity  = EV + Cash − Total Debt
Implied share price = Equity / Shares Outstanding
```

- If shares outstanding are missing, `implied_share_price` stays **null** — never
  fabricated — while equity value is still reported. Audit raises a WARNING.
- Upside/downside compares the implied price to the latest market close (Yahoo).

## 9. Sensitivity analysis

`calculate_sensitivity_matrix` sweeps two drivers at a time, holding all else fixed:

- **WACC × terminal growth** heatmap (perpetuity method)
- **WACC × exit multiple** heatmap
- **Tornado**: one-at-a-time perturbation of each key driver around the base case,
  ranked by impact on implied share price.

Recomputation uses the same engine path as the base case — sensitivities cannot drift
from the headline number.

## 10. Scenarios

Base / Bull / Bear presets and custom scenarios are expressed as **deltas** on
assumption keys (growth, margin, WACC, terminal growth, exit multiple…). Applying a
scenario routes through `apply_overrides` (bounds-validated) and `recompute_view`, so
scenario values carry the same provenance (`USER OVERRIDE`) as hand-entered ones.

## 11. Comparables

Peer multiples (EV/EBITDA, P/E, EV/Sales…) from a curated universe or user-supplied
tickers, with a minimum of 2 valid peers — below that the comps page reports
insufficient data rather than a thin multiple.

## 12. Precedence & provenance

Every value carries a source type:

| SourceType | Meaning |
|---|---|
| `PUBLIC_API` | Retrieved from SEC / Yahoo / FRED |
| `USER_INPUT` | Entered by the user (data review, forms) |
| `USER_OVERRIDE` | Explicit override in assumptions/scenarios |
| `MODEL_ASSUMPTION` | An explicit modeling choice (e.g. MRP, target growth) |
| `CALCULATED` | Produced by a pure math function |

Precedence when resolving a value: **USER OVERRIDE > user input > model estimate**.
The Assumptions page always shows which tier won and lets the user revert.

## Optional LLM usage

An LLM (OpenAI / Groq / Google, via `core/llm.py`) may be configured to write narrative
paragraphs in the report. It is used **only for text**: no number is ever produced,
transformed or validated by a model. Without a key the pipeline runs identically with
templated prose.
