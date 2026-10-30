"""Battery energy storage plant: converter lag, power and energy limits, SOC integration.

Pure step functions. Positive power is discharge (injection). The converter follows its
setpoint with a first-order lag (time constant ``tau``); the stored energy changes by
``-P / eta_d`` when discharging and ``-P eta_c`` when charging. The battery management
system keeps the energy inside the usable window by clipping the power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nordic_bess.config import Config

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class BatteryParams:
    """Plant parameters (units in the names)."""

    p_max_mw: float
    e_min_mwh: float
    e_max_mwh: float
    eta_c: float
    eta_d: float
    tau_s: float

    @classmethod
    def from_config(cls, cfg: Config, tau_s: float | None = None) -> BatteryParams:
        b = cfg.bess
        return cls(
            p_max_mw=b.p_max_mw,
            e_min_mwh=b.e_min_mwh,
            e_max_mwh=b.e_max_mwh,
            eta_c=b.eta_charge,
            eta_d=b.eta_discharge,
            tau_s=b.converter_time_constant_s if tau_s is None else tau_s,
        )


def lag_coefficient(dt_s: float, tau_s: float) -> float:
    """Exact discretisation of a first-order lag: ``1 - exp(-dt / tau)`` (1 when tau = 0)."""
    return 1.0 if tau_s <= 0 else 1.0 - math.exp(-dt_s / tau_s)


def energy_limited_power(p_mw: float, e_mwh: float, dt_s: float, b: BatteryParams) -> float:
    """Clip a power so the energy stays inside ``[e_min, e_max]`` over one step [MW]."""
    h = dt_s / SECONDS_PER_HOUR
    p_dis_max = max(e_mwh - b.e_min_mwh, 0.0) * b.eta_d / h
    p_ch_max = max(b.e_max_mwh - e_mwh, 0.0) / b.eta_c / h
    return min(max(p_mw, -p_ch_max), p_dis_max)


def energy_step(e_mwh: float, p_mw: float, dt_s: float, eta_c: float, eta_d: float) -> float:
    """Stored energy after one step [MWh] for a constant power ``p_mw`` (+ = discharge)."""
    h = dt_s / SECONDS_PER_HOUR
    if p_mw >= 0:
        return e_mwh - p_mw / eta_d * h
    return e_mwh - p_mw * eta_c * h


def plant_step(
    p_out_mw: float, e_mwh: float, p_set_mw: float, dt_s: float, b: BatteryParams, alpha: float
) -> tuple[float, float, bool]:
    """Advance converter and storage by one step.

    Args:
        p_out_mw: Converter output at the start of the step [MW].
        e_mwh: Stored energy at the start of the step [MWh].
        p_set_mw: Power setpoint from the controller [MW].
        dt_s: Step length [s].
        b: Plant parameters.
        alpha: Lag coefficient from :func:`lag_coefficient`.

    Returns:
        ``(p_out, e_next, energy_limited)``: output held during the step, stored energy at
        its end and whether the BMS clipped the power.
    """
    p_req = min(max(p_set_mw, -b.p_max_mw), b.p_max_mw)
    p_lag = p_out_mw + alpha * (p_req - p_out_mw)
    p_out = energy_limited_power(p_lag, e_mwh, dt_s, b)
    limited = abs(p_out - p_lag) > 1e-12
    return p_out, energy_step(e_mwh, p_out, dt_s, b.eta_c, b.eta_d), limited
