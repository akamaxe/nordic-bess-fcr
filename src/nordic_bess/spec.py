"""Definitions fixed by the Nordic FCR technical requirements v1.1 (not tunable parameters).

Product frequency bands follow Table 1 and section 3; tunable reservation factors,
NEM rates and Table 11 thresholds live in the config instead (they are expected to be
re-evaluated by the TSOs, section 3.5).
"""

from __future__ import annotations

from enum import StrEnum

F_NOMINAL_HZ = 50.0
NORMAL_BAND_HZ = (49.9, 50.1)  # standard frequency range, "the normal band" (3.5.1)


class Product(StrEnum):
    FCR_N = "FCR_N"
    FCR_D_UP = "FCR_D_UP"
    FCR_D_DOWN = "FCR_D_DOWN"


#: Zero-activation reference frequency f0 per product (eq. 19).
F0_HZ = {Product.FCR_N: 50.0, Product.FCR_D_UP: 49.9, Product.FCR_D_DOWN: 50.1}
#: Frequency change for full activation, delta f_max (eq. 23; Table 1 bands).
DF_MAX_HZ = {Product.FCR_N: 0.1, Product.FCR_D_UP: 0.4, Product.FCR_D_DOWN: 0.4}
#: Frequency of 100 % activation (Table 1).
F_FULL_HZ = {Product.FCR_N: 49.9, Product.FCR_D_UP: 49.5, Product.FCR_D_DOWN: 50.5}
