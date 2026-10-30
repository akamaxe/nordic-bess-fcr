"""Backtest KPIs: revenue per stream, EUR/MW-year, cycles, product shares.

FCR activation energy is not part of the planning model (it is checked in the asset
simulation), so revenues here are capacity revenues plus day-ahead trading.
"""

from __future__ import annotations

import pandas as pd

from nordic_bess.market.milp import MilpParams
from nordic_bess.market.strategies import BacktestResult

HOURS_PER_YEAR = 8760.0
STREAMS = {
    "rev_da_eur": "Day-ahead",
    "rev_fcr_n_eur": "FCR-N",
    "rev_fcr_dup_eur": "FCR-D up",
    "rev_fcr_ddown_eur": "FCR-D down",
    "cost_degradation_eur": "Degradation",
}
CAPACITY_COLUMNS = {"FCR-N": "c_n_mw", "FCR-D up": "c_dup_mw", "FCR-D down": "c_ddown_mw"}


def revenue_streams(schedule: pd.DataFrame, dt_h: float, c_deg_eur_per_mwh: float) -> pd.DataFrame:
    """Revenue per period and stream in EUR (degradation as a negative revenue).

    Day-ahead: ``lambda (p_d - p_c) dt``; FCR: ``pi c dt`` (EUR/MW/h x MW x h);
    degradation: ``-c_deg p_d dt``.
    """
    s = schedule
    out = pd.DataFrame(index=s.index)
    out["rev_da_eur"] = s["price_da_eur_per_mwh"] * (s["p_d_mw"] - s["p_c_mw"]) * dt_h
    out["rev_fcr_n_eur"] = s["price_fcr_n_eur_per_mw_h"] * s["c_n_mw"] * dt_h
    out["rev_fcr_dup_eur"] = s["price_fcr_dup_eur_per_mw_h"] * s["c_dup_mw"] * dt_h
    out["rev_fcr_ddown_eur"] = s["price_fcr_ddown_eur_per_mw_h"] * s["c_ddown_mw"] * dt_h
    out["cost_degradation_eur"] = -c_deg_eur_per_mwh * s["p_d_mw"] * dt_h
    out["net_eur"] = out[list(STREAMS)].sum(axis=1)
    return out


def summarise(result: BacktestResult, params: MilpParams, min_capacity_mw: float = 1e-3) -> dict:
    """One row of ``results/revenue_summary.csv`` for a backtest result.

    EUR per MW-year is the net revenue divided by ``P_max`` and scaled to 8760 h.
    Equivalent full cycles count day-ahead discharge throughput over the usable window.
    """
    s, dt = result.schedule, result.dt_h
    rev = revenue_streams(s, dt, params.c_deg_eur_per_mwh)
    hours = len(s) * dt
    scale = HOURS_PER_YEAR / hours
    e_usable = params.e_max_mwh - params.e_min_mwh
    row = {"strategy": result.strategy.name, "description": result.strategy.description}
    for col in [*STREAMS, "net_eur"]:
        row[col] = float(rev[col].sum())
    row["eur_per_mw_year"] = row["net_eur"] / params.p_max_mw * scale
    row["discharge_mwh"] = float((s["p_d_mw"] * dt).sum())
    row["cycles_per_year"] = row["discharge_mwh"] / e_usable * scale
    for label, col in CAPACITY_COLUMNS.items():
        key = label.lower().replace(" ", "_").replace("-", "_")
        row[f"share_hours_{key}"] = float((s[col] > min_capacity_mw).mean())
        row[f"mean_mw_{key}"] = float(s[col].mean())
    row["hours"] = hours
    row["solve_time_s"] = result.solve_time_s
    row["max_constraint_violation"] = result.max_violation
    return row


def monthly_revenue(result: BacktestResult, params: MilpParams) -> pd.DataFrame:
    """Revenue per calendar month (UTC) and stream in EUR."""
    rev = revenue_streams(result.schedule, result.dt_h, params.c_deg_eur_per_mwh)
    monthly = rev[list(STREAMS)].groupby(rev.index.tz_localize(None).to_period("M")).sum()
    return monthly.rename(columns=STREAMS)


def allocation_by_hour_and_month(result: BacktestResult) -> dict[str, pd.DataFrame]:
    """Mean capacity sold [MW] per product, hour of day (UTC) x month."""
    s = result.schedule
    hourly = s.groupby(s.index.floor("h"))[list(CAPACITY_COLUMNS.values())].first()
    key = [hourly.index.hour, hourly.index.month]
    out = {}
    for label, col in CAPACITY_COLUMNS.items():
        out[label] = hourly[col].groupby(key).mean().unstack(1)
    return out


def binding_shares(result: BacktestResult, params: MilpParams, tol: float = 1e-5) -> dict:
    """Share of periods in which the power and energy reservation constraints bind."""
    s, p = result.schedule, params
    net = s["p_d_mw"] - s["p_c_mw"]
    cn, cu, cd = s["c_n_mw"], s["c_dup_mw"], s["c_ddown_mw"]
    up = p.p_max_mw - (net + p.power_factor_n * cn + cu + p.power_factor_d_opposite * cd)
    down = (net - p.power_factor_n * cn - p.power_factor_d_opposite * cu - cd) + p.p_max_mw
    e_min = s[["e_start_mwh", "e_end_mwh"]].min(axis=1)
    e_max = s[["e_start_mwh", "e_end_mwh"]].max(axis=1)
    e_up = p.eta_d * (e_min - p.e_min_mwh) - (p.energy_hours_n * cn + p.energy_hours_d * cu)
    e_dn = (p.e_max_mwh - e_max) / p.eta_c - (p.energy_hours_n * cn + p.energy_hours_d * cd)
    return {
        "c3_up_power": float((up < tol).mean()),
        "c4_down_power": float((down < tol).mean()),
        "c5_up_energy": float((e_up < tol).mean()),
        "c6_down_energy": float((e_dn < tol).mean()),
    }
