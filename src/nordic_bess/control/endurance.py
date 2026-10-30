"""Real-time endurance of LER units (FCR v1.1, section 3.5.4, eq. 27-28)."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike


def endurance_minutes(
    e_mwh: ArrayLike,
    e_min_mwh: ArrayLike,
    e_max_mwh: ArrayLike,
    p_setpoint_mw: ArrayLike,
    c_up_mw: ArrayLike,
    c_down_mw: ArrayLike,
    p_inflow_mw: ArrayLike = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Upwards and downwards endurance in minutes (FCR v1.1, eq. 27 and 28).

    ``L_up = |(E - E_min) / (P_setpoint + C_up - P_inflow)| * 60`` and
    ``L_down = |(E_max - E) / (P_inflow - P_setpoint + C_down)| * 60``; the setpoint
    includes the NEM power (3.5.4). A zero denominator gives an infinite endurance.
    Callers report 0 in a direction where AEM is active.
    """
    e = np.asarray(e_mwh, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        den_up = np.asarray(p_setpoint_mw) + np.asarray(c_up_mw) - np.asarray(p_inflow_mw)
        den_dn = np.asarray(p_inflow_mw) - np.asarray(p_setpoint_mw) + np.asarray(c_down_mw)
        l_up = np.abs((e - np.asarray(e_min_mwh)) / den_up) * 60.0
        l_dn = np.abs((np.asarray(e_max_mwh) - e) / den_dn) * 60.0
    l_up = np.where(den_up == 0, np.inf, l_up)
    l_dn = np.where(den_dn == 0, np.inf, l_dn)
    return l_up, l_dn
