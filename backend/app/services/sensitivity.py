"""Sensitivity stage — two-way tables and single-factor (tornado) swings.

Results are *conditional ranges*, never predictions, and cells where the model
is undefined (e.g. WACC <= terminal growth) are None with the reason recorded.
"""
from __future__ import annotations

from collections.abc import Callable

from ..core.errors import AppError
from ..schemas.valuation import DcfResult, SensitivityResult, SensitivityTable, TornadoItem
from ..valuation import calculate_sensitivity_matrix, tornado_swing

# Tornado input spans: (override key, low delta, high delta)
TORNADO_SPECS: list[tuple[str, float, float, str]] = [
    ("__wacc__", -0.010, +0.010, "WACC ± 1.0pp"),
    ("terminal_growth", -0.005, +0.005, "Terminal growth ± 0.5pp"),
    ("beta", -0.15, +0.15, "Beta ± 0.15"),
    ("risk_free_rate", -0.005, +0.005, "Risk-free rate ± 0.5pp"),
    ("market_risk_premium", -0.010, +0.010, "MRP ± 1.0pp"),
    ("revenue_growth", -0.020, +0.020, "Revenue growth ± 2.0pp"),
    ("ebit_margin", -0.020, +0.020, "EBIT margin ± 2.0pp"),
    ("capex_pct", -0.010, +0.010, "CapEx / revenue ± 1.0pp"),
    ("nwc_pct", -0.010, +0.010, "NWC / revenue ± 1.0pp"),
    ("exit_multiple", -2.0, +2.0, "Exit multiple ± 2.0x"),
]


def _safe_price(compute: Callable[..., object], *, forced_wacc: float | None = None,
                overrides: dict[str, float] | None = None,
                forced_terminal: str | None = None) -> float | None:
    """Run a compute pass; any model failure yields None (cell left empty)."""
    try:
        core = compute(overrides or {}, forced_wacc=forced_wacc,
                       forced_terminal=forced_terminal)
        return core.dcf.implied_share_price
    except AppError:
        return None
    except Exception:  # noqa: BLE001 — sensitivity must never crash the pipeline
        return None


def build_sensitivity(
    compute: Callable[..., object],
    base_values: dict[str, float | None],
    base_dcf: DcfResult,
    *,
    wacc_step: float = 0.0025,
    growth_step: float = 0.0025,
) -> SensitivityResult:
    """compute(overrides, forced_wacc=...) -> CoreResult"""
    notes: list[str] = []
    tables: list[SensitivityTable] = []

    base_wacc = base_dcf.discount_rate
    base_growth = base_values.get("terminal_growth") or 0.025
    base_exit = base_values.get("exit_multiple") or 10.0
    base_price = base_dcf.implied_share_price

    # ---- WACC x terminal growth ---------------------------------------------
    waccs = [round(base_wacc + i * wacc_step, 6) for i in range(-2, 3)]
    growths = [round(base_growth + i * growth_step, 6) for i in range(-2, 3)]

    def price_at_growth(w: float, g: float) -> float | None:
        return _safe_price(compute, forced_wacc=w, overrides={"terminal_growth": g})

    grid = calculate_sensitivity_matrix(price_at_growth, waccs, growths)
    tables.append(SensitivityTable(
        key="wacc_vs_growth",
        title="Implied Share Price — WACC vs Terminal Growth",
        row_label="WACC", col_label="Terminal Growth",
        row_values=grid.row_values, col_values=grid.col_values,
        matrix=grid.matrix, base_value=base_price,
        base_row=base_wacc, base_col=base_growth, unit="price",
        note="Each cell is a full DCF re-run with that WACC and terminal growth.",
    ))
    undefined = len(grid.errors)
    if undefined:
        notes.append(
            f"{undefined} cell(s) undefined because WACC <= terminal growth — "
            "the perpetuity formula has no finite value there."
        )

    # ---- WACC x exit multiple ------------------------------------------------
    exits = [round(base_exit + i * 0.5, 4) for i in range(-2, 3)]

    def price_at_exit(w: float, m: float) -> float | None:
        return _safe_price(compute, forced_wacc=w,
                           overrides={"exit_multiple": m},
                           forced_terminal="exit_multiple")

    grid2 = calculate_sensitivity_matrix(price_at_exit, waccs, exits)
    tables.append(SensitivityTable(
        key="wacc_vs_exit",
        title="Implied Share Price — WACC vs Exit EV/EBITDA Multiple",
        row_label="WACC", col_label="Exit Multiple",
        row_values=grid2.row_values, col_values=grid2.col_values,
        matrix=grid2.matrix, base_value=base_price,
        base_row=base_wacc, base_col=base_exit, unit="price",
        note="Exit-multiple terminal method; terminal EBITDA held at the forecast level.",
    ))

    # ---- tornado --------------------------------------------------------------
    tornado: list[TornadoItem] = []
    for key, lo_delta, hi_delta, label in TORNADO_SPECS:
        if key == "__wacc__":
            low = _safe_price(compute, forced_wacc=round(base_wacc + lo_delta, 6))
            high = _safe_price(compute, forced_wacc=round(base_wacc + hi_delta, 6))
            lo_v, hi_v = round(base_wacc + lo_delta, 6), round(base_wacc + hi_delta, 6)
        else:
            base_v = base_values.get(key)
            if base_v is None:
                continue
            lo_v, hi_v = base_v + lo_delta, base_v + hi_delta
            low = _safe_price(compute, overrides={key: lo_v})
            high = _safe_price(compute, overrides={key: hi_v})
        swing = tornado_swing(base_price, low, high)
        tornado.append(TornadoItem(
            input_key=key, label=label, low=lo_v, high=hi_v,
            low_result=low, high_result=high, base_result=base_price,
            swing=swing,
            note="Range conditional on this input moving while all others stay fixed.",
        ))
    tornado.sort(key=lambda t: (t.swing is None, -(t.swing or 0.0)))
    notes.append(
        "Sensitivity results are conditional ranges, not predictions or price targets."
    )

    return SensitivityResult(tables=tables, tornado=tornado,
                             base_implied_price=base_price, notes=notes)
