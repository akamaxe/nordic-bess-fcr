"""Synthetic FCR units for testing the evaluators (PLAN M4 acceptance).

A synthetic unit responds to the test frequency with ``gain`` times the ideal droop
activation, delayed by ``delay_s`` and filtered by a first-order lag ``tau_s``.
"""

from __future__ import annotations

import math

import numpy as np

from nordic_bess.compliance.signals import TestSignal
from nordic_bess.control.droop import activation


def synthetic_response(
    sig: TestSignal,
    c_mw: float,
    gain: float = 1.0,
    delay_s: float = 0.0,
    tau_s: float = 0.0,
    saturate_fcr_d: bool = True,
) -> np.ndarray:
    """Activated power [MW] of a synthetic unit for a test signal."""
    ideal = gain * activation(sig.product, sig.f_hz, c_mw, saturate_fcr_d=saturate_fcr_d)
    shift = int(round(delay_s / sig.dt_s))
    delayed = np.r_[np.full(shift, ideal[0]), ideal[: len(ideal) - shift]] if shift else ideal
    if tau_s <= 0:
        return delayed
    alpha = 1.0 - math.exp(-sig.dt_s / tau_s)
    out = np.empty_like(delayed)
    y = delayed[0]
    for i, u in enumerate(delayed):
        y += alpha * (u - y)
        out[i] = y
    return out
