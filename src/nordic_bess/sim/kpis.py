"""KPIs of a simulation run (PLAN M3): SOC, NEM/AEM time, availability, tracking error."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nordic_bess.plant.battery import SECONDS_PER_HOUR, BatteryParams

NEM_COLUMNS = ("p_nem_n_mw", "p_nem_dup_mw", "p_nem_ddown_mw")
SUFFIXES = ("n", "dup", "ddown")


def _dt_s(df: pd.DataFrame) -> float:
    return float(df["t_s"].iloc[1] - df["t_s"].iloc[0]) if len(df) > 1 else 1.0


def energy_balance_error(df: pd.DataFrame, b: BatteryParams, e0_mwh: float) -> float:
    """|E_end - E_0 - sum of (eta_c P_ch - P_dis / eta_d) dt| in MWh (should be ~0)."""
    p = df["p_out_mw"].to_numpy()
    h = _dt_s(df) / SECONDS_PER_HOUR
    change = (np.where(p < 0, -p * b.eta_c, 0.0) - np.where(p > 0, p / b.eta_d, 0.0)).sum() * h
    return float(abs(df["e_mwh"].iloc[-1] - e0_mwh - change))


def tracking_error_mw(df: pd.DataFrame) -> pd.Series:
    """Output minus the ideal response: baseline + NEM power + droop at nominal f_ref [MW].

    Non-zero when the converter lags, AEM shifts the reference or the BMS clips power.
    """
    nem = df[list(NEM_COLUMNS)].sum(axis=1)
    return df["p_out_mw"] - (df["p_base_mw"] + nem + df["p_ideal_mw"])


def fcr_unavailable(df: pd.DataFrame) -> pd.Series:
    """True where a sold product cannot be delivered.

    A product is unavailable while its AEM is active (FCR v1.1, 3.5.2) or while the BMS
    clips power in the direction the product needs: an empty battery (output below
    setpoint) blocks FCR-N and FCR-D up, a full one blocks FCR-N and FCR-D down. A clip
    in the other direction is a day-ahead delivery shortfall, reported separately.
    """
    n, up, down = (df[f"c_{s}_mw"] > 0 for s in SUFFIXES)
    empty = df["energy_limited"] & (df["p_set_mw"] > df["p_out_mw"])
    full = df["energy_limited"] & (df["p_set_mw"] < df["p_out_mw"])
    aem = (n & df["aem_n"]) | (up & df["aem_dup"]) | (down & df["aem_ddown"])
    return aem | (empty & (n | up)) | (full & (n | down))


def simulation_kpis(df: pd.DataFrame, b: BatteryParams, e0_mwh: float) -> dict:
    """Summary of a run: energy, NEM/AEM shares, unavailability, throughput, tracking."""
    dt = _dt_s(df)
    h = dt / SECONDS_PER_HOUR
    p = df["p_out_mw"]
    e_range = b.e_max_mwh - b.e_min_mwh
    soc_fcr = (df["e_mwh"] - b.e_min_mwh) / e_range
    err = tracking_error_mw(df)
    unavailable = fcr_unavailable(df)
    clipped = (df["p_set_mw"] - df["p_out_mw"]).where(df["energy_limited"], 0.0)
    kpis = {
        "duration_h": len(df) * h,
        "e_start_mwh": e0_mwh,
        "e_end_mwh": float(df["e_mwh"].iloc[-1]),
        "soc_fcr_min": float(soc_fcr.min()),
        "soc_fcr_mean": float(soc_fcr.mean()),
        "soc_fcr_max": float(soc_fcr.max()),
        "unavailable_minutes": float(unavailable.sum() * dt / 60.0),
        "energy_limited_minutes": float(df["energy_limited"].sum() * dt / 60.0),
        "energy_shortfall_mwh": float(clipped.abs().sum() * h),
        "throughput_discharge_mwh": float(p.clip(lower=0).sum() * h),
        "throughput_charge_mwh": float((-p).clip(lower=0).sum() * h),
        "nem_energy_mwh": float(df[list(NEM_COLUMNS)].sum(axis=1).sum() * h),
        "tracking_rmse_mw": float(np.sqrt((err**2).mean())),
        "tracking_max_abs_mw": float(err.abs().max()),
        "energy_balance_error_mwh": energy_balance_error(df, b, e0_mwh),
    }
    kpis["equivalent_cycles"] = kpis["throughput_discharge_mwh"] / e_range
    for sfx in SUFFIXES:
        kpis[f"nem_share_{sfx}"] = float((df[f"nem_current_{sfx}"] != 0).mean())
        kpis[f"aem_share_{sfx}"] = float(df[f"aem_{sfx}"].mean())
    return kpis
