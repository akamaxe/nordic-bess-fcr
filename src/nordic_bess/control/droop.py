"""Per-product proportional (droop) FCR activation.

``P_X = C_X / df_max,X * (f_ref,X - f_meas,X)`` (FCR v1.1, eq. 23, which reduces to the
steady-state droop of eq. 12 with ``f_ref = f0``), where ``f_meas,X`` is the measured
frequency saturated per product (eq. 20-22). Positive power is upward regulation
(injection). FCR-D output saturates at the sold volume, which is allowed for a unit
without an LFSM obligation (section 3.6.2). The functions accept scalars or arrays.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

from nordic_bess.spec import DF_MAX_HZ, F0_HZ, Product


def saturated_frequency(product: Product, f_hz: ArrayLike) -> np.ndarray:
    """Measured frequency saturated per product [Hz] (FCR v1.1, eq. 20-22).

    FCR-N: clipped to 49.9-50.1 Hz; FCR-D up: at most 49.9 Hz; FCR-D down: at least 50.1 Hz.
    """
    f = np.asarray(f_hz, dtype=float)
    if product is Product.FCR_N:
        return np.clip(f, 49.9, 50.1)
    if product is Product.FCR_D_UP:
        return np.minimum(f, 49.9)
    return np.maximum(f, 50.1)


def activation(
    product: Product,
    f_hz: ArrayLike,
    c_mw: ArrayLike,
    f_ref_hz: ArrayLike | None = None,
    saturate_fcr_d: bool = True,
) -> np.ndarray:
    """Activated power of one product [MW] (FCR v1.1, eq. 12 and 23, Table 1).

    Args:
        product: FCR product.
        f_hz: Measured frequency [Hz].
        c_mw: Sold capacity [MW].
        f_ref_hz: Reference frequency [Hz]; defaults to f0 of the product (no AEM).
        saturate_fcr_d: Limit FCR-D output to the sold volume (section 3.6.2).
    """
    c = np.asarray(c_mw, dtype=float)
    f_ref = F0_HZ[product] if f_ref_hz is None else np.asarray(f_ref_hz, dtype=float)
    p = c / DF_MAX_HZ[product] * (f_ref - saturated_frequency(product, f_hz))
    if saturate_fcr_d and product is Product.FCR_D_UP:
        p = np.minimum(p, c)
    elif saturate_fcr_d and product is Product.FCR_D_DOWN:
        p = np.maximum(p, -c)
    return p


def activation_scalar(
    product: Product, f_hz: float, c_mw: float, f_ref_hz: float, saturate_fcr_d: bool = True
) -> float:
    """Scalar equivalent of :func:`activation` for the simulation loop (same equations)."""
    if product is Product.FCR_N:
        p = c_mw / 0.1 * (f_ref_hz - min(max(f_hz, 49.9), 50.1))
    elif product is Product.FCR_D_UP:
        p = c_mw / 0.4 * (f_ref_hz - min(f_hz, 49.9))
        if saturate_fcr_d:
            p = min(p, c_mw)
    else:
        p = c_mw / 0.4 * (f_ref_hz - max(f_hz, 50.1))
        if saturate_fcr_d:
            p = max(p, -c_mw)
    return p


def total_activation(
    f_hz: ArrayLike, c_n_mw: ArrayLike, c_dup_mw: ArrayLike, c_ddown_mw: ArrayLike
) -> np.ndarray:
    """Steady-state sum of FCR-N and FCR-D activation [MW] (FCR v1.1, section 3.6.1)."""
    return (
        activation(Product.FCR_N, f_hz, c_n_mw)
        + activation(Product.FCR_D_UP, f_hz, c_dup_mw)
        + activation(Product.FCR_D_DOWN, f_hz, c_ddown_mw)
    )
