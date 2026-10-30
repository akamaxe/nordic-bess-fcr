"""Normal and Alert State Energy Management for limited energy reservoirs (FCR v1.1, 3.5).

Pure building blocks; the simulator (``nordic_bess.sim.engine``) owns the state
(hysteresis latches and the 300-sample rolling windows of eq. 15 and 18).

Thresholds are expressed as stored energy [MWh] rather than SOC. For a single product
they equal Table 11 (SOC x E, with E the energy range used for FCR). With several
products the FCR-D reserves sit at the edges of the range and the FCR-N thresholds are
shifted inwards by the energy reserved for FCR-D in the same direction, so FCR-N
activation never depletes the FCR-D reserve (section 3.5, Table 10). This stacking is
our implementation choice; the requirements leave it to the provider.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nordic_bess.config import FcrRequirementsConfig, ThresholdMinutes
from nordic_bess.spec import F0_HZ, NORMAL_BAND_HZ, Product

NAN = float("nan")


@dataclass(frozen=True)
class EnergyThresholds:
    """Table 11 thresholds of one product as stored energy [MWh]; NaN where N.A."""

    aem_enable_low: float
    aem_disable_low: float
    nem_enable_low: float
    nem_disable_low: float
    nem_disable_high: float
    nem_enable_high: float
    aem_disable_high: float
    aem_enable_high: float


def table11_thresholds(
    product: Product,
    c_mw: float,
    e_low_mwh: float,
    e_high_mwh: float,
    minutes: ThresholdMinutes,
) -> EnergyThresholds:
    """Energy thresholds for one product inside ``[e_low, e_high]`` (FCR v1.1, Table 11).

    ``e_low + C t / 60`` on the low side and ``e_high - C t / 60`` on the high side, with
    ``t`` the Table 11 minutes. FCR-D up has no high-side thresholds and FCR-D down no
    low-side thresholds (N.A. in Table 11).
    """

    def low(t_min: float) -> float:
        return NAN if product is Product.FCR_D_DOWN else e_low_mwh + c_mw * t_min / 60.0

    def high(t_min: float) -> float:
        return NAN if product is Product.FCR_D_UP else e_high_mwh - c_mw * t_min / 60.0

    return EnergyThresholds(
        aem_enable_low=low(minutes.aem_enable),
        aem_disable_low=low(minutes.aem_disable),
        nem_enable_low=low(minutes.nem_enable),
        nem_disable_low=low(minutes.nem_disable),
        nem_disable_high=high(minutes.nem_disable),
        nem_enable_high=high(minutes.nem_enable),
        aem_disable_high=high(minutes.aem_disable),
        aem_enable_high=high(minutes.aem_enable),
    )


def stacked_thresholds(
    c_n_mw: float,
    c_dup_mw: float,
    c_ddown_mw: float,
    e_min_mwh: float,
    e_max_mwh: float,
    fcr: FcrRequirementsConfig,
) -> dict[Product, EnergyThresholds]:
    """Thresholds of all products when they are provided together (see module docstring)."""
    reserve_dup = fcr.energy_hours_d * c_dup_mw
    reserve_ddown = fcr.energy_hours_d * c_ddown_mw
    return {
        Product.FCR_N: table11_thresholds(
            Product.FCR_N,
            c_n_mw,
            e_min_mwh + reserve_dup,
            e_max_mwh - reserve_ddown,
            fcr.thresholds_fcr_n,
        ),
        Product.FCR_D_UP: table11_thresholds(
            Product.FCR_D_UP, c_dup_mw, e_min_mwh, e_max_mwh, fcr.thresholds_fcr_d
        ),
        Product.FCR_D_DOWN: table11_thresholds(
            Product.FCR_D_DOWN, c_ddown_mw, e_min_mwh, e_max_mwh, fcr.thresholds_fcr_d
        ),
    }


def in_normal_band(f_hz: float) -> bool:
    """True inside the standard frequency range 49.9 < f < 50.1 Hz (eq. 14)."""
    return NORMAL_BAND_HZ[0] < f_hz < NORMAL_BAND_HZ[1]


def nem_update(
    f_hz: float, e_mwh: float, low_active: bool, high_active: bool, th: EnergyThresholds
) -> tuple[int, bool, bool]:
    """One 1 s update of NEM_allowed with hysteresis (FCR v1.1, eq. 14, Table 11).

    NEM enters when the frequency is in the normal band and the energy is outside the
    enable thresholds; it leaves when the energy is back inside the disable thresholds
    or the frequency leaves the normal band. NaN thresholds never trigger.

    Returns:
        ``(nem_allowed, low_active, high_active)`` with ``nem_allowed`` in {-1, 0, +1}:
        -1 = SOC too low (charge), +1 = SOC too high (discharge).
    """
    if not in_normal_band(f_hz):
        return 0, False, False
    low = e_mwh < (th.nem_disable_low if low_active else th.nem_enable_low)
    high = e_mwh > (th.nem_disable_high if high_active else th.nem_enable_high)
    if low:
        return -1, True, False
    if high:
        return 1, False, True
    return 0, False, False


def aem_update(
    e_mwh: float, low_active: bool, high_active: bool, th: EnergyThresholds
) -> tuple[bool, bool]:
    """One 1 s update of the AEM latches with hysteresis (FCR v1.1, 3.5.2, Table 11)."""
    low = e_mwh < (th.aem_disable_low if low_active else th.aem_enable_low)
    high = e_mwh > (th.aem_disable_high if high_active else th.aem_enable_high)
    return low, high


def f_aem(product: Product, f_hz: float, aem_active: bool) -> float:
    """Frequency fed to the AEM reference average (FCR v1.1, eq. 19-22)."""
    if not aem_active:
        return F0_HZ[product]
    if product is Product.FCR_N:
        return min(max(f_hz, 49.9), 50.1)
    if product is Product.FCR_D_UP:
        return min(f_hz, 49.9)
    return max(f_hz, 50.1)


def nem_rate(product: Product, fcr: FcrRequirementsConfig) -> float:
    """NEM power as a share of the sold capacity (eq. 16-17): 0.34 FCR-N, 0.20 FCR-D."""
    return fcr.nem_rate_n if product is Product.FCR_N else fcr.nem_rate_d


def limit_output(product: Product, p_tot_mw: float, c_mw: float, p_nem_max_mw: float) -> float:
    """Output limits per product (FCR v1.1, eq. 24-26).

    FCR-N stays within +-(C + P_NEM,max); FCR-D up never goes below -P_NEM,max (it may
    not use the FCR-D down power) and FCR-D down never above +P_NEM,max.
    """
    if product is Product.FCR_N:
        bound = c_mw + p_nem_max_mw
        return min(max(p_tot_mw, -bound), bound)
    if product is Product.FCR_D_UP:
        return max(p_tot_mw, -p_nem_max_mw)
    return min(p_tot_mw, p_nem_max_mw)


def threshold_is_set(value: float) -> bool:
    return not math.isnan(value)
