"""Frequency-domain evaluation from sine tests (FCR v1.1, sections 3.2-3.4).

- :func:`fit_sine` - least-squares sine fit with the known test period (3.4.1)
- :func:`transfer_point` - normalised F(jw) from one sine test (eq. 6-9)
- :func:`power_system` - G(jw) with Table 7 parameters (eq. 11)
- :func:`nyquist_distance` - stability margin of G0 = F G (eq. 10, Requirement 8)
- :func:`closed_loop_ratio` - performance check of Requirement 9

Sign convention (docs/FCR_SPEC_NOTES.md, resolved against PDF p. 27-29): F is defined
from the frequency control error (f_ref - f) to power, so G0 = F * G.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nordic_bess.spec import Product


@dataclass(frozen=True)
class SineFit:
    """``y(t) = amplitude * sin(w t + phase) + offset``; ``fitted`` is the zero-mean sine."""

    amplitude: float
    phase_rad: float
    offset: float
    fitted: np.ndarray


def fit_sine(t_s: np.ndarray, y: np.ndarray, period_s: float) -> SineFit:
    """Least-squares fit of a sine with known period plus a constant (FCR v1.1, 3.4.1)."""
    w = 2 * np.pi / period_s
    a = np.column_stack([np.sin(w * t_s), np.cos(w * t_s), np.ones_like(t_s)])
    (s, c, k), *_ = np.linalg.lstsq(a, y, rcond=None)
    return SineFit(
        amplitude=float(np.hypot(s, c)),
        phase_rad=float(np.arctan2(c, s)),
        offset=float(k),
        fitted=s * np.sin(w * t_s) + c * np.cos(w * t_s),
    )


@dataclass(frozen=True)
class TransferPoint:
    """One measured point of the normalised transfer function F(jw)."""

    period_s: float
    omega_rad_s: float
    f_complex: complex
    linearity_ratio: float  # Requirement 10 measure for this period

    @property
    def gain(self) -> float:
        return abs(self.f_complex)

    @property
    def phase_deg(self) -> float:
        return float(np.degrees(np.angle(self.f_complex)))


def transfer_point(
    t_s: np.ndarray,
    control_error_hz: np.ndarray,
    p_mw: np.ndarray,
    period_s: float,
    df_band_hz: float,
    dp_theoretical_mw: float,
) -> TransferPoint:
    """Normalised F(jw) from stationary sine periods (FCR v1.1, eq. 6-9) and the
    dynamic-linearity measure of Requirement 10.

    ``|F| = (A_P / A_f) (|df_X| / |dP_X,th|)`` and ``phi = phase(P) - phase(e)``, negative
    when the power lags the control error ``e = f_ref - f``.
    """
    fe = fit_sine(t_s, control_error_hz, period_s)
    fp = fit_sine(t_s, p_mw, period_s)
    gain = fp.amplitude / fe.amplitude * df_band_hz / abs(dp_theoretical_mw)
    phase = np.angle(np.exp(1j * (fp.phase_rad - fe.phase_rad)))
    baseline_free = p_mw - fp.offset
    ratio = linearity_ratio(baseline_free, fp.fitted)
    return TransferPoint(period_s, 2 * np.pi / period_s, gain * np.exp(1j * phase), ratio)


def linearity_ratio(p_measured: np.ndarray, p_fitted: np.ndarray) -> float:
    """Requirement 10: ``sqrt(sum (P_mv - P_est)^2) / sqrt(sum (P_est - mean P_est)^2)``."""
    num = np.sqrt(np.sum((p_measured - p_fitted) ** 2))
    den = np.sqrt(np.sum((p_fitted - np.mean(p_fitted)) ** 2))
    return float(num / den) if den > 0 else float("inf")


@dataclass(frozen=True)
class PowerSystemParams:
    """Table 7 parameters of the Nordic power system model (eq. 11)."""

    dp_mw: float
    df_hz: float
    f0_hz: float
    s_n_mw: float
    h_s: float
    k_f_pu_per_hz: float


#: FCR v1.1, Table 7 (H = kinetic energy / S_n).
TABLE7 = {
    ("N", "performance"): PowerSystemParams(600.0, 0.1, 50.0, 42000.0, 190000.0 / 42000.0, 0.01),
    ("N", "stability"): PowerSystemParams(600.0, 0.1, 50.0, 23000.0, 120000.0 / 23000.0, 0.01),
    ("D", "performance"): PowerSystemParams(1450.0, 0.4, 50.0, 42000.0, 190000.0 / 42000.0, 0.01),
    ("D", "stability"): PowerSystemParams(1450.0, 0.4, 50.0, 23000.0, 120000.0 / 23000.0, 0.01),
}
NYQUIST_RADIUS = 0.43  # Requirement 8
NYQUIST_MARGIN = 0.95  # accepted 95 % margin
K_MARGIN = 0.95  # Requirement 9
K_RED_DYN_MIN = {Product.FCR_N: 0.9, Product.FCR_D_UP: 0.75, Product.FCR_D_DOWN: 0.75}


def table7(product: Product, case: str) -> PowerSystemParams:
    return TABLE7[("N" if product is Product.FCR_N else "D", case)]


def power_system(omega: np.ndarray, p: PowerSystemParams) -> np.ndarray:
    """``G(jw) = (dP / df) (f0 / S_n) / (2 H jw + K_f f0)`` in p.u. (FCR v1.1, eq. 11)."""
    w = np.asarray(omega, dtype=float)
    return (
        (p.dp_mw / p.df_hz)
        * (p.f0_hz / p.s_n_mw)
        / (2 * p.h_s * 1j * w + p.k_f_pu_per_hz * p.f0_hz)
    )


def disturbance_profile(omega: np.ndarray) -> np.ndarray:
    """``D(jw) = 1 / (70 jw + 1)`` (FCR v1.1, section 3.3)."""
    return 1.0 / (70.0 * 1j * np.asarray(omega, dtype=float) + 1.0)


def interpolate_curve(points: np.ndarray, per_segment: int = 200) -> np.ndarray:
    """Linear interpolation in the complex plane between consecutive points (3.2)."""
    if len(points) < 2:
        return np.asarray(points, dtype=complex)
    s = np.linspace(0.0, 1.0, per_segment, endpoint=False)
    parts = [a + (b - a) * s for a, b in zip(points[:-1], points[1:], strict=True)]
    return np.concatenate([*parts, points[-1:]])


@dataclass(frozen=True)
class NyquistResult:
    min_distance: float
    crosses_left_of_circle: bool  # crosses the real axis left of -1 + r (encirclement)


def nyquist_distance(g0_points: np.ndarray) -> NyquistResult:
    """Smallest distance of the interpolated Nyquist curve to (-1, 0j) (Requirement 8).

    ``g0_points`` must be ordered by frequency. The curve must also pass on the right
    side of the circle: a crossing of the negative real axis left of ``-1 + r`` fails.
    """
    curve = interpolate_curve(np.asarray(g0_points, dtype=complex))
    dist = float(np.min(np.abs(curve + 1.0)))
    re, im = curve.real, curve.imag
    sign_change = np.flatnonzero(np.sign(im[:-1]) * np.sign(im[1:]) < 0)
    crossings = [re[i] - im[i] * (re[i + 1] - re[i]) / (im[i + 1] - im[i]) for i in sign_change]
    left = any(x < -1.0 + NYQUIST_RADIUS for x in crossings)
    return NyquistResult(min_distance=dist, crosses_left_of_circle=bool(left))


def closed_loop_ratio(f_values: np.ndarray, omega: np.ndarray, p: PowerSystemParams, k_red=1.0):
    """Requirement 9 ratio ``K_margin |G / (1 + F G / K_red)| / |1 / D|`` (< 1 passes)."""
    g = power_system(omega, p)
    gc = K_MARGIN * np.abs(g / (1.0 + np.asarray(f_values) / k_red * g))
    return gc / np.abs(1.0 / disturbance_profile(omega))


def interpolate_f(points: list[TransferPoint], n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """F(jw) on a dense log-spaced grid between the measured periods (complex linear)."""
    pts = sorted(points, key=lambda tp: tp.omega_rad_s)
    w = np.array([tp.omega_rad_s for tp in pts])
    f = np.array([tp.f_complex for tp in pts])
    grid = np.geomspace(w[0], w[-1], n)
    real = np.interp(np.log(grid), np.log(w), f.real)
    imag = np.interp(np.log(grid), np.log(w), f.imag)
    return grid, real + 1j * imag
