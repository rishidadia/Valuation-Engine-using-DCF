"""Sensitivity analysis: two-way matrices and tornado (single-factor) swings.

Sensitivity results are *ranges conditional on inputs*, never predictions.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.errors import ValidationError


@dataclass(frozen=True)
class SensitivityGrid:
    row_values: list[float]
    col_values: list[float]
    matrix: list[list[float | None]]  # None where the model is undefined (e.g. WACC <= g)
    errors: dict[tuple[int, int], str]


def make_grid(base: float, steps: int = 4, step: float = 0.005,
              symmetric: bool = True) -> list[float]:
    """Simple +/- steps grid around a base value."""
    if steps < 1:
        raise ValidationError("steps must be >= 1")
    vals = [base + i * step for i in range(-steps, steps + 1)]
    if symmetric:
        return [round(v, 6) for v in vals]
    return [round(v, 6) for v in vals]


def calculate_sensitivity_matrix(
    fn: Callable[[float, float], float | None],
    row_values: list[float],
    col_values: list[float],
) -> SensitivityGrid:
    """Evaluate fn(row, col) over the grid; None where fn raises/returns None.

    `fn` must be a pure function of the two grid inputs (e.g. rebuild DCF with
    a different WACC and terminal growth).
    """
    if not row_values or not col_values:
        raise ValidationError("Sensitivity grids require at least one row and one column value")
    matrix: list[list[float | None]] = []
    errors: dict[tuple[int, int], str] = {}
    for i, r in enumerate(row_values):
        row_out: list[float | None] = []
        for j, c in enumerate(col_values):
            try:
                out = fn(r, c)
                row_out.append(None if out is None else float(out))
            except Exception as exc:  # model undefined at this point (e.g. WACC<=g)
                row_out.append(None)
                errors[(i, j)] = str(getattr(exc, "detail", exc))
        matrix.append(row_out)
    return SensitivityGrid(row_values=list(row_values), col_values=list(col_values),
                           matrix=matrix, errors=errors)


def tornado_swing(base_result: float | None, low_result: float | None,
                  high_result: float | None) -> float | None:
    """Magnitude of the valuation swing caused by one input moving across its range."""
    vals = [v for v in (low_result, high_result) if v is not None]
    if not vals or base_result is None:
        return None
    return max(abs(max(vals) - base_result), abs(min(vals) - base_result))


def summarize_range(values: list[float | None]) -> dict:
    """Min/max/median of the defined cells of a sensitivity table."""
    clean = [v for v in values if v is not None]
    if not clean:
        return {}
    clean.sort()
    n = len(clean)
    median = clean[n // 2] if n % 2 else (clean[n // 2 - 1] + clean[n // 2]) / 2
    return {"min": clean[0], "max": clean[-1], "median": median, "count": n}
