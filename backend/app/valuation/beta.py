"""Beta estimation: market regression, Hamada unlevering/relevering, peers.

Unlever: Beta_U = Beta_L / [1 + (1 - T)(D/E)]
Relever: Beta_L = Beta_U x [1 + (1 - T)(D/E)]
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.errors import ValidationError


def calculate_unlevered_beta(levered_beta: float, debt_equity: float, tax_rate: float) -> float:
    """Hamada: Beta_U = Beta_L / [1 + (1 - T)(D/E)]."""
    if levered_beta is None:
        raise ValidationError("levered_beta is required")
    if debt_equity is None or debt_equity < 0:
        raise ValidationError(f"debt/equity ratio must be >= 0 (got {debt_equity})")
    if not 0 <= tax_rate <= 0.75:
        raise ValidationError(f"tax_rate={tax_rate} outside [0, 0.75]")
    denom = 1.0 + (1.0 - tax_rate) * debt_equity
    if denom <= 0:
        raise ValidationError("Invalid capital structure for unlevering beta")
    return levered_beta / denom


def calculate_relevered_beta(unlevered_beta: float, debt_equity: float, tax_rate: float) -> float:
    """Hamada: Beta_L = Beta_U x [1 + (1 - T)(D/E)]."""
    if unlevered_beta is None:
        raise ValidationError("unlevered_beta is required")
    if debt_equity is None or debt_equity < 0:
        raise ValidationError(f"debt/equity ratio must be >= 0 (got {debt_equity})")
    if not 0 <= tax_rate <= 0.75:
        raise ValidationError(f"tax_rate={tax_rate} outside [0, 0.75]")
    return unlevered_beta * (1.0 + (1.0 - tax_rate) * debt_equity)


def regression_beta(stock_returns: np.ndarray, market_returns: np.ndarray) -> tuple[float, float, float]:
    """OLS beta of a stock against a market index.

    Returns (beta, alpha, r_squared). Requires aligned return series.
    """
    x = np.asarray(market_returns, dtype=float)
    y = np.asarray(stock_returns, dtype=float)
    if x.shape != y.shape:
        raise ValidationError(f"Return series length mismatch: {x.shape} vs {y.shape}")
    if len(x) < 12:
        raise ValidationError(
            f"Need at least 12 observations to estimate beta (got {len(x)})",
            hint="Fetch a longer price history or provide beta manually.",
        )
    if np.allclose(x, x[0]):
        raise ValidationError("Market returns have zero variance; beta is undefined")

    var = np.var(x)
    beta = float(np.cov(y, x, ddof=1)[0, 1] / var)
    alpha = float(np.mean(y) - beta * np.mean(x))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum((y - (alpha + beta * x)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, alpha, r2


def aggregate_beta(unlevered_betas: list[float], method: str = "median") -> float:
    """Central tendency of peer unlevered betas."""
    vals = [b for b in unlevered_betas if b is not None and not math.isnan(b)]
    if not vals:
        raise ValidationError("No usable peer betas to aggregate")
    if method == "median":
        arr = np.sort(np.array(vals))
        mid = len(arr) // 2
        if len(arr) % 2:
            return float(arr[mid])
        return float((arr[mid - 1] + arr[mid]) / 2.0)
    if method == "mean":
        return float(np.mean(vals))
    raise ValidationError(f"Unknown beta aggregation method: {method}")


@dataclass
class ComparableBetaResult:
    unlevered_betas: list[tuple[str, float]]
    peer_unlevered_median: float
    peer_unlevered_mean: float
    relevered_beta: float
    target_de: float
    tax_rate: float
    method: str
    formula_lines: list[str]


def comparable_beta_estimate(
    peers: list[tuple[str, float, float, float]],  # (ticker, levered_beta, peer_d/e, peer_tax)
    target_de: float,
    target_tax_rate: float,
    method: str = "median",
) -> ComparableBetaResult:
    """Unlever peer betas, aggregate, relever at the target's D/E and tax rate."""
    if not peers:
        raise ValidationError("No comparable companies supplied for beta estimation")
    if target_de < 0:
        raise ValidationError("target D/E must be >= 0")

    unlev: list[tuple[str, float]] = []
    lines: list[str] = []
    for ticker, bl, de, t in peers:
        bu = calculate_unlevered_beta(bl, de, t)
        unlev.append((ticker, bu))
        lines.append(f"{ticker}: {bl:.2f} / (1 + (1 - {t:.0%}) x {de:.2f}) = {bu:.3f}")

    med = aggregate_beta([b for _, b in unlev], "median")
    mean = aggregate_beta([b for _, b in unlev], "mean")
    chosen = med if method == "median" else mean
    lines.append(f"{method} unlevered beta = {chosen:.3f}")
    bl_target = calculate_relevered_beta(chosen, target_de, target_tax_rate)
    lines.append(
        f"Relevered = {chosen:.3f} x (1 + (1 - {target_tax_rate:.0%}) x {target_de:.2f}) = {bl_target:.3f}"
    )
    return ComparableBetaResult(
        unlevered_betas=unlev,
        peer_unlevered_median=med,
        peer_unlevered_mean=mean,
        relevered_beta=bl_target,
        target_de=target_de,
        tax_rate=target_tax_rate,
        method=method,
        formula_lines=lines,
    )
