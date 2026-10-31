"""Requirement evaluators (FCR v1.1, Requirements 1-4, 8-10 and 12).

Every evaluator works on time series (test frequency and activated power) and returns
:class:`RequirementResult` objects, so the same code scores synthetic units, the Python
BESS model and the Simulink twin. ``p_mw`` is always the *activated* power: output
minus the baseline, positive upwards.

Steady-state power ``P_ss`` of a hold is the mean over its last
``steady_state_window_s`` seconds (the requirements do not fix the averaging window;
see docs/assumptions.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nordic_bess.compliance import freqdomain as fd
from nordic_bess.compliance.signals import TestSignal
from nordic_bess.spec import DF_MAX_HZ, F0_HZ, Product

R2_SHARE = 0.86  # Requirement 2
R3_SECONDS = 3.2  # Requirement 3
R4_SECONDS = 2.5  # Requirement 4
T_EVAL_S = 7.5  # Requirements 2 and 3
T_NADIR_S = 4.4  # Requirement 4: nadir after the start of ramp 1
R4_WINDOW_S = 40.0
K_RED_SS_MIN = {Product.FCR_N: 0.9, Product.FCR_D_UP: 0.75, Product.FCR_D_DOWN: 0.75}


@dataclass(frozen=True)
class RequirementResult:
    """Outcome of one requirement check."""

    requirement: str
    product: str
    measured: float
    threshold: str
    passed: bool
    explanation: str
    unit: str = ""


def _mean_window(t: np.ndarray, p: np.ndarray, t_end: float, window_s: float) -> float:
    mask = (t >= t_end - window_s - 1e-9) & (t < t_end - 1e-9)
    if not mask.any():
        raise ValueError(f"no samples before t = {t_end} s")
    return float(np.mean(p[mask]))


def _value_at(t: np.ndarray, p: np.ndarray, t_query: float) -> float:
    return float(np.interp(t_query, t, p))


def _integral(t: np.ndarray, y: np.ndarray, t0: float, t1: float) -> float:
    """Trapezoidal integral of y over [t0, t1] with interpolated end points."""
    inner = (t > t0) & (t < t1)
    tt = np.r_[t0, t[inner], t1]
    yy = np.r_[_value_at(t, y, t0), y[inner], _value_at(t, y, t1)]
    return float(np.sum((tt[1:] - tt[:-1]) * (yy[1:] + yy[:-1]) / 2.0))


def k_red_needed(delivered_mw: float, theoretical_mw: float) -> float:
    """Largest reduction factor that removes an under-delivery beyond 5 % (eq. 3, 5)."""
    return min(1.0, abs(delivered_mw) / (0.95 * abs(theoretical_mw)))


def _ratio_result(req, product, ratio, lo, hi, what, k_red, k_min) -> RequirementResult:
    passed = lo <= ratio <= hi
    note = f"{what}: deviation {ratio:+.3f} of |dP_th|, allowed [{lo:+.2f}, {hi:+.2f}]"
    if not passed and ratio < lo:
        verdict = "prequalifies with" if k_red >= k_min else "fails even with"
        note += f"; K_red,ss = {k_red:.3f} needed ({verdict} K_red >= {k_min})"
    return RequirementResult(req, product, ratio, f"[{lo}, {hi}]", passed, note, "p.u.")


def evaluate_r1_fcr_n(
    sig: TestSignal, p_mw: np.ndarray, dp_th_mw: float, window_s: float
) -> list[RequirementResult]:
    """Requirement 1 for FCR-N from the step sequence (FCR v1.1, 3.1.1, eq. 1-3)."""
    t = sig.t_s
    pss = {
        k: _mean_window(t, p_mw, sig.segment(k).t_end_s, window_s)
        for k in ("step0", "step1", "step2", "step3")
    }
    base = 0.5 * (pss["step0"] + pss["step3"])
    dp1, dp2 = pss["step1"] - base, pss["step2"] - base  # eq. 1, 2
    th = abs(dp_th_mw)
    up = (dp1 - th) / th
    down = (dp2 + th) / th
    k_up, k_down = k_red_needed(dp1, th), k_red_needed(dp2, th)
    k_min = K_RED_SS_MIN[Product.FCR_N]
    return [
        _ratio_result("R1 up", "FCR-N", up, -0.05, 0.20, f"dP_ss,1 = {dp1:.3f} MW", k_up, k_min),
        _ratio_result(
            "R1 down", "FCR-N", down, -0.20, 0.05, f"dP_ss,2 = {dp2:.3f} MW", k_down, k_min
        ),
    ]


def evaluate_fcr_d_ramp(
    sig: TestSignal, p_mw: np.ndarray, dp_th_mw: float, window_s: float
) -> list[RequirementResult]:
    """Requirements 1, 2, 3 and 4 for FCR-D from the fast ramp test (3.1.2, eq. 4)."""
    product = sig.product
    up = product is Product.FCR_D_UP
    name = "FCR-D up" if up else "FCR-D down"
    sgn = 1.0 if up else -1.0
    t, th = sig.t_s, abs(dp_th_mw)
    k_min = K_RED_SS_MIN[product]
    results = []

    # Requirement 1: P_ss,3 - P_ss,4 against |dP_th|.
    pss3 = _mean_window(t, p_mw, sig.segment("ramp3").t_end_s, window_s)
    pss4 = _mean_window(t, p_mw, sig.segment("ramp4").t_end_s, window_s)
    dss = pss3 - pss4
    if up:
        results.append(
            _ratio_result(
                "R1",
                name,
                (dss - th) / th,
                -0.05,
                0.20,
                f"P_ss,3 - P_ss,4 = {dss:.3f} MW",
                k_red_needed(dss, th),
                k_min,
            )
        )
    else:
        results.append(
            _ratio_result(
                "R1",
                name,
                (dss + th) / th,
                -0.20,
                0.05,
                f"P_ss,3 - P_ss,4 = {dss:.3f} MW",
                k_red_needed(dss, th),
                k_min,
            )
        )

    # Requirements 2 and 3 on ramp 5, relative to the power just before the ramp.
    r5 = sig.segment("ramp5")
    t0 = r5.t_start_s
    p0 = _value_at(t, p_mw, t0)
    dp = sgn * (p_mw - p0)  # activated power in the product direction
    dp75 = _value_at(t, dp, t0 + T_EVAL_S)
    e75 = _integral(t, dp, t0, t0 + T_EVAL_S)
    results.append(
        RequirementResult(
            "R2",
            name,
            dp75 / th,
            f">= {R2_SHARE}",
            dp75 >= R2_SHARE * th,
            f"dP(7.5 s) = {dp75:.3f} MW = {dp75 / th:.3f} |dP_th| (need {R2_SHARE})",
            "p.u.",
        )
    )
    after = (t > t0 + T_EVAL_S) & (t < sig.segment("ramp6").t_start_s)
    sag = float(np.max(dp75 - dp[after], initial=0.0)) / th
    results.append(
        RequirementResult(
            "R2 hold",
            name,
            sag,
            "<= 0.01",
            sag <= 0.01,
            f"largest drop below dP(7.5 s) before ramp 6: {sag:.4f} |dP_th| "
            "(small damped oscillations accepted; 1 % tolerance used)",
            "p.u.",
        )
    )
    results.append(
        RequirementResult(
            "R3",
            name,
            e75 / th,
            f">= {R3_SECONDS} s",
            e75 >= R3_SECONDS * th,
            f"E(7.5 s) = {e75:.2f} MWs = {e75 / th:.2f} s x |dP_th| (need {R3_SECONDS} s)",
            "s",
        )
    )

    # Requirement 4: deactivation after the nadir of ramps 1-2.
    r1 = sig.segment("ramp1")
    t_n = r1.t_start_s + T_NADIR_S
    p_before = _value_at(t, p_mw, r1.t_start_s)
    dp4 = sgn * (p_mw - p_before)
    level = min(abs(_value_at(t, dp4, t_n)), 0.5 * th)
    ks = np.linspace(t_n, t_n + R4_WINDOW_S, 401)
    excess = dp4 - level
    worst = max(_integral(t, excess, t_n, k) for k in ks[1:])
    results.append(
        RequirementResult(
            "R4",
            name,
            worst / th,
            f"<= {R4_SECONDS} s",
            worst <= R4_SECONDS * th,
            f"max excess energy after the nadir = {worst:.2f} MWs = {worst / th:.2f} s x |dP_th|",
            "s",
        )
    )
    return results


def evaluate_frequency_domain(
    product: Product, points: list[fd.TransferPoint]
) -> list[RequirementResult]:
    """Requirements 8 (stability), 9 (performance) and 10 (linearity) from sine tests."""
    name = {Product.FCR_N: "FCR-N", Product.FCR_D_UP: "FCR-D up", Product.FCR_D_DOWN: "FCR-D down"}[
        product
    ]
    pts = sorted(points, key=lambda tp: tp.omega_rad_s)
    w = np.array([tp.omega_rad_s for tp in pts])
    f = np.array([tp.f_complex for tp in pts])
    results = []

    g0 = f * fd.power_system(w, fd.table7(product, "stability"))
    nyq = fd.nyquist_distance(g0)
    limit = fd.NYQUIST_RADIUS * fd.NYQUIST_MARGIN
    passed = nyq.min_distance > limit and not nyq.crosses_left_of_circle
    results.append(
        RequirementResult(
            "R8",
            name,
            nyq.min_distance,
            f"> {limit:.4f} (0.43 x 0.95)",
            passed,
            f"min distance of G0 = F G to (-1, 0j): {nyq.min_distance:.3f}"
            + (
                "; curve crosses the real axis left of the circle"
                if nyq.crosses_left_of_circle
                else ""
            ),
            "p.u.",
        )
    )

    grid, f_dense = fd.interpolate_f(pts)
    perf = fd.table7(product, "performance")
    ratio = float(np.max(fd.closed_loop_ratio(f_dense, grid, perf)))
    note = f"max K_margin |G/(1+FG)| / |1/D| = {ratio:.3f} over the tested periods"
    if ratio >= 1.0:
        k = _k_red_dyn(f_dense, grid, perf)
        k_min = fd.K_RED_DYN_MIN[product]
        note += f"; K_red,dyn = {k:.3f} needed (minimum {k_min})" if k else "; no K_red,dyn helps"
    results.append(RequirementResult("R9", name, ratio, "< 1", ratio < 1.0, note, "p.u."))

    worst = max(pts, key=lambda tp: tp.linearity_ratio)
    results.append(
        RequirementResult(
            "R10",
            name,
            worst.linearity_ratio,
            "< 1",
            worst.linearity_ratio < 1.0,
            f"worst normalised RMS error of the fitted sine: {worst.linearity_ratio:.3f} "
            f"(T = {worst.period_s:g} s)",
            "p.u.",
        )
    )
    return results


def _k_red_dyn(f_dense, grid, perf) -> float | None:
    """Largest K_red,dyn in (0, 1] with ratio < 1, found by bisection on F / K_red."""
    lo, hi = 0.05, 1.0
    if np.max(fd.closed_loop_ratio(f_dense, grid, perf, lo)) >= 1.0:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if np.max(fd.closed_loop_ratio(f_dense, grid, perf, mid)) < 1.0:
            lo = mid
        else:
            hi = mid
    return lo


def evaluate_sine_tests(
    product: Product,
    runs: list[tuple[TestSignal, np.ndarray]],
    dp_th_mw: float,
    stationary: dict[float, int],
) -> list[fd.TransferPoint]:
    """Transfer points from sine-test runs, using the last stationary periods of each."""
    band = DF_MAX_HZ[product]
    f_ref = F0_HZ[product]  # control error e = f_ref - f (eq. 7-8)
    points = []
    for sig, p in runs:
        period = _period(sig)
        n_stat = stationary[period]
        mask = sig.t_s >= sig.t_s[-1] + sig.dt_s - n_stat * period - 1e-9
        err = f_ref - sig.f_hz[mask]
        points.append(fd.transfer_point(sig.t_s[mask], err, p[mask], period, band, dp_th_mw))
    return points


def _period(sig: TestSignal) -> float:
    return float(sig.name.rsplit("_", 1)[1].removesuffix("s"))
