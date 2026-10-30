"""Daily MILP: FCR-N, FCR-D up/down capacity and day-ahead arbitrage (PLAN M2).

One model covers one UTC day of ``24 * periods_per_hour`` day-ahead periods; FCR
capacities are hourly blocks. With ``periods_per_hour = 1`` this is exactly the v0.1
formulation in docs/PLAN.md (constraints 1-7); with 4 it is the M2b variant with
15-minute day-ahead prices and hourly FCR blocks.

Constraints (FCR v1.1, Table 10 for the LER power and energy reservation):

1. ``p_d <= P_max u``, ``p_c <= P_max (1 - u)`` (no simultaneous charge and discharge)
2. ``e[k+1] = e[k] + (eta_c p_c - p_d / eta_d) dt``, ``E_min <= e <= E_max``
3. ``(p_d - p_c) + 1.34 c_N + c_Dup + 0.20 c_Ddown <= P_max``  (upward power)
4. ``(p_d - p_c) - 1.34 c_N - 0.20 c_Dup - c_Ddown >= -P_max`` (downward power)
5. ``eta_d (e_k - E_min) >= 1 h c_N + 1/3 h c_Dup`` at both ends of every period
6. ``(E_max - e_k) / eta_c >= 1 h c_N + 1/3 h c_Ddown`` at both ends of every period
7. ``c <= 70 MW`` per product; ``e[0] = e[end] = e_0`` (daily cycle)

The coefficients 1.34, 0.20, 1 h and 1/3 h come from ``fcr_requirements`` in the config.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.contrib.appsi.base import TerminationCondition
from pyomo.contrib.appsi.solvers import Highs

from nordic_bess.config import Config, SolverConfig

HOURS_PER_DAY = 24


@dataclass(frozen=True)
class Strategy:
    """Which revenue streams the MILP may use; disabled ones are fixed to zero."""

    name: str
    description: str
    day_ahead: bool
    fcr_n: bool
    fcr_dup: bool
    fcr_ddown: bool


@dataclass(frozen=True)
class MilpParams:
    """Battery and FCR-reservation parameters of the daily MILP (units in the names)."""

    p_max_mw: float
    e_min_mwh: float
    e_max_mwh: float
    e0_mwh: float
    eta_c: float
    eta_d: float
    c_deg_eur_per_mwh: float
    power_factor_n: float
    power_factor_d_opposite: float
    energy_hours_n: float
    energy_hours_d: float
    max_per_product_mw: float

    @classmethod
    def from_config(cls, cfg: Config) -> MilpParams:
        b, f = cfg.bess, cfg.fcr
        return cls(
            p_max_mw=b.p_max_mw,
            e_min_mwh=b.e_min_mwh,
            e_max_mwh=b.e_max_mwh,
            e0_mwh=b.e_target_mwh,
            eta_c=b.eta_charge,
            eta_d=b.eta_discharge,
            c_deg_eur_per_mwh=b.degradation_cost_eur_per_mwh,
            power_factor_n=f.power_factor_n,
            power_factor_d_opposite=f.power_factor_d_opposite,
            energy_hours_n=f.energy_hours_n,
            energy_hours_d=f.energy_hours_d,
            max_per_product_mw=f.max_per_product_mw,
        )


@dataclass(frozen=True)
class DayPrices:
    """Prices for one day: day-ahead per period [EUR/MWh], FCR per hour [EUR/MW/h]."""

    da_eur_per_mwh: np.ndarray
    fcr_n_eur_per_mw_h: np.ndarray
    fcr_dup_eur_per_mw_h: np.ndarray
    fcr_ddown_eur_per_mw_h: np.ndarray


@dataclass(frozen=True)
class DaySolution:
    """Optimal schedule of one day.

    ``periods`` has one row per day-ahead period with columns ``p_c_mw``, ``p_d_mw``,
    ``e_start_mwh``, ``e_end_mwh``, ``c_n_mw``, ``c_dup_mw``, ``c_ddown_mw`` (hourly
    capacities repeated on their periods) and the prices.
    """

    periods: pd.DataFrame
    objective_eur: float
    solve_time_s: float
    dt_h: float


class DailyMilp:
    """Persistent daily MILP for one strategy; prices change from day to day."""

    def __init__(
        self,
        params: MilpParams,
        strategy: Strategy,
        solver: SolverConfig,
        periods_per_hour: int = 1,
    ) -> None:
        if solver.name != "appsi_highs":
            raise ValueError(f"unsupported solver {solver.name!r}; use appsi_highs")
        self.params = params
        self.strategy = strategy
        self.pph = int(periods_per_hour)
        self.n_periods = HOURS_PER_DAY * self.pph
        self.dt_h = 1.0 / self.pph
        self.model = self._build()
        self.solver = Highs()
        self.solver.config.mip_gap = solver.mip_rel_gap
        self.solver.config.time_limit = solver.time_limit_s

    def _build(self) -> pyo.ConcreteModel:
        p, dt, pph = self.params, self.dt_h, self.pph
        m = pyo.ConcreteModel(name=f"daily_milp_{self.strategy.name}")
        m.P = pyo.RangeSet(0, self.n_periods - 1)  # day-ahead periods
        m.K = pyo.RangeSet(0, self.n_periods)  # energy boundaries
        m.H = pyo.RangeSet(0, HOURS_PER_DAY - 1)  # FCR hourly blocks

        m.lam = pyo.Param(m.P, mutable=True, initialize=0.0)
        m.pi_n = pyo.Param(m.H, mutable=True, initialize=0.0)
        m.pi_dup = pyo.Param(m.H, mutable=True, initialize=0.0)
        m.pi_ddown = pyo.Param(m.H, mutable=True, initialize=0.0)

        m.p_c = pyo.Var(m.P, bounds=(0.0, p.p_max_mw))
        m.p_d = pyo.Var(m.P, bounds=(0.0, p.p_max_mw))
        m.u = pyo.Var(m.P, domain=pyo.Binary)
        cap = (0.0, p.max_per_product_mw)  # constraint 7
        m.c_n = pyo.Var(m.H, bounds=cap)
        m.c_dup = pyo.Var(m.H, bounds=cap)
        m.c_ddown = pyo.Var(m.H, bounds=cap)
        m.e = pyo.Var(m.K, bounds=(p.e_min_mwh, p.e_max_mwh))

        def h(t: int) -> int:
            return t // pph

        m.c1_discharge = pyo.Constraint(m.P, rule=lambda m, t: m.p_d[t] <= p.p_max_mw * m.u[t])
        m.c1_charge = pyo.Constraint(m.P, rule=lambda m, t: m.p_c[t] <= p.p_max_mw * (1 - m.u[t]))
        m.c2_balance = pyo.Constraint(
            m.P,
            rule=lambda m, t: m.e[t + 1] == m.e[t] + (p.eta_c * m.p_c[t] - m.p_d[t] / p.eta_d) * dt,
        )
        m.c3_up_power = pyo.Constraint(
            m.P,
            rule=lambda m, t: (
                (m.p_d[t] - m.p_c[t])
                + p.power_factor_n * m.c_n[h(t)]
                + m.c_dup[h(t)]
                + p.power_factor_d_opposite * m.c_ddown[h(t)]
                <= p.p_max_mw
            ),
        )
        m.c4_down_power = pyo.Constraint(
            m.P,
            rule=lambda m, t: (
                (m.p_d[t] - m.p_c[t])
                - p.power_factor_n * m.c_n[h(t)]
                - p.power_factor_d_opposite * m.c_dup[h(t)]
                - m.c_ddown[h(t)]
                >= -p.p_max_mw
            ),
        )
        ends = pyo.Set(initialize=[0, 1])
        m.c5_up_energy = pyo.Constraint(
            m.P,
            ends,
            rule=lambda m, t, j: (
                p.eta_d * (m.e[t + j] - p.e_min_mwh)
                >= p.energy_hours_n * m.c_n[h(t)] + p.energy_hours_d * m.c_dup[h(t)]
            ),
        )
        m.c6_down_energy = pyo.Constraint(
            m.P,
            ends,
            rule=lambda m, t, j: (
                (p.e_max_mwh - m.e[t + j]) / p.eta_c
                >= p.energy_hours_n * m.c_n[h(t)] + p.energy_hours_d * m.c_ddown[h(t)]
            ),
        )
        m.c7_start = pyo.Constraint(expr=m.e[0] == p.e0_mwh)
        m.c7_end = pyo.Constraint(expr=m.e[self.n_periods] == p.e0_mwh)

        m.obj = pyo.Objective(
            expr=sum(
                m.lam[t] * (m.p_d[t] - m.p_c[t]) * dt - p.c_deg_eur_per_mwh * m.p_d[t] * dt
                for t in m.P
            )
            + sum(
                m.pi_n[k] * m.c_n[k] + m.pi_dup[k] * m.c_dup[k] + m.pi_ddown[k] * m.c_ddown[k]
                for k in m.H
            ),
            sense=pyo.maximize,
        )

        s = self.strategy
        if not s.day_ahead:
            for t in m.P:
                m.p_c[t].fix(0.0)
                m.p_d[t].fix(0.0)
                m.u[t].fix(0)
        for enabled, var in ((s.fcr_n, m.c_n), (s.fcr_dup, m.c_dup), (s.fcr_ddown, m.c_ddown)):
            if not enabled:
                for k in m.H:
                    var[k].fix(0.0)
        return m

    def solve(self, prices: DayPrices, fixed_capacity: np.ndarray | None = None) -> DaySolution:
        """Solve one day.

        Args:
            prices: Day-ahead prices per period and FCR prices per hour.
            fixed_capacity: Optional ``(24, 3)`` array of FCR-N, FCR-D up, FCR-D down
                capacities [MW] decided earlier (second stage of the sequential M2b
                decision). Products disabled by the strategy stay at zero.

        Raises:
            RuntimeError: If the solver does not return an optimal solution.
        """
        m = self.model
        da = np.asarray(prices.da_eur_per_mwh, dtype=float)
        if da.shape != (self.n_periods,):
            raise ValueError(f"expected {self.n_periods} day-ahead prices, got {da.shape}")
        for t in m.P:
            m.lam[t].set_value(float(da[t]))
        for name, values in (
            ("pi_n", prices.fcr_n_eur_per_mw_h),
            ("pi_dup", prices.fcr_dup_eur_per_mw_h),
            ("pi_ddown", prices.fcr_ddown_eur_per_mw_h),
        ):
            values = np.asarray(values, dtype=float)
            if values.shape != (HOURS_PER_DAY,):
                raise ValueError(f"expected 24 hourly FCR prices for {name}")
            param = getattr(m, name)
            for k in m.H:
                param[k].set_value(float(values[k]))

        s = self.strategy
        flags = (s.fcr_n, s.fcr_dup, s.fcr_ddown)
        for j, (enabled, var) in enumerate(zip(flags, (m.c_n, m.c_dup, m.c_ddown), strict=True)):
            for k in m.H:
                if not enabled:
                    var[k].fix(0.0)
                elif fixed_capacity is not None:
                    var[k].fix(float(max(fixed_capacity[k, j], 0.0)))
                else:
                    var[k].unfix()

        t0 = time.perf_counter()
        res = self.solver.solve(m)
        elapsed = time.perf_counter() - t0
        if res.termination_condition != TerminationCondition.optimal:
            raise RuntimeError(f"{s.name}: solver returned {res.termination_condition}")
        return DaySolution(
            periods=self._extract(da, prices),
            objective_eur=float(pyo.value(m.obj)),
            solve_time_s=elapsed,
            dt_h=self.dt_h,
        )

    def _extract(self, da: np.ndarray, prices: DayPrices) -> pd.DataFrame:
        m, pph = self.model, self.pph
        e = np.array([pyo.value(m.e[k]) for k in m.K])
        hours = np.arange(self.n_periods) // pph

        def hourly(var) -> np.ndarray:
            return np.array([pyo.value(var[k]) for k in m.H])[hours]

        return pd.DataFrame(
            {
                "p_c_mw": [pyo.value(m.p_c[t]) for t in m.P],
                "p_d_mw": [pyo.value(m.p_d[t]) for t in m.P],
                "e_start_mwh": e[:-1],
                "e_end_mwh": e[1:],
                "c_n_mw": hourly(m.c_n),
                "c_dup_mw": hourly(m.c_dup),
                "c_ddown_mw": hourly(m.c_ddown),
                "price_da_eur_per_mwh": da,
                "price_fcr_n_eur_per_mw_h": np.asarray(prices.fcr_n_eur_per_mw_h)[hours],
                "price_fcr_dup_eur_per_mw_h": np.asarray(prices.fcr_dup_eur_per_mw_h)[hours],
                "price_fcr_ddown_eur_per_mw_h": np.asarray(prices.fcr_ddown_eur_per_mw_h)[hours],
            }
        )


def constraint_violations(periods: pd.DataFrame, params: MilpParams, dt_h: float) -> dict:
    """Largest violation of constraints 1-7 in a solved schedule (0 = satisfied).

    Evaluated on the solution values, independently of the Pyomo model, so a modelling
    error cannot hide a violation (PLAN M2 acceptance).

    Returns:
        Mapping from constraint name to its largest violation in MW or MWh.
    """
    p = params
    pc, pd_ = periods["p_c_mw"].to_numpy(), periods["p_d_mw"].to_numpy()
    cn, cu, cd = (periods[c].to_numpy() for c in ("c_n_mw", "c_dup_mw", "c_ddown_mw"))
    e0, e1 = periods["e_start_mwh"].to_numpy(), periods["e_end_mwh"].to_numpy()
    net = pd_ - pc
    up = net + p.power_factor_n * cn + cu + p.power_factor_d_opposite * cd - p.p_max_mw
    down = -p.p_max_mw - (net - p.power_factor_n * cn - p.power_factor_d_opposite * cu - cd)
    need_up = p.energy_hours_n * cn + p.energy_hours_d * cu
    need_down = p.energy_hours_n * cn + p.energy_hours_d * cd
    e_up = np.maximum(
        need_up - p.eta_d * (e0 - p.e_min_mwh), need_up - p.eta_d * (e1 - p.e_min_mwh)
    )
    e_dn = np.maximum(
        need_down - (p.e_max_mwh - e0) / p.eta_c, need_down - (p.e_max_mwh - e1) / p.eta_c
    )
    balance = e1 - e0 - (p.eta_c * pc - pd_ / p.eta_d) * dt_h
    window = np.maximum(p.e_min_mwh - np.minimum(e0, e1), np.maximum(e0, e1) - p.e_max_mwh)
    cycle = abs(e0[0] - p.e0_mwh) + abs(e1[-1] - p.e0_mwh)
    return {
        "c1_simultaneous_mw": float(np.max(np.minimum(pc, pd_), initial=0.0)),
        "c2_balance_mwh": float(np.max(np.abs(balance), initial=0.0)),
        "c2_window_mwh": float(max(np.max(window, initial=0.0), 0.0)),
        "c3_up_power_mw": float(max(np.max(up, initial=0.0), 0.0)),
        "c4_down_power_mw": float(max(np.max(down, initial=0.0), 0.0)),
        "c5_up_energy_mwh": float(max(np.max(e_up, initial=0.0), 0.0)),
        "c6_down_energy_mwh": float(max(np.max(e_dn, initial=0.0), 0.0)),
        "c7_cap_mw": float(max(np.max([cn, cu, cd]) - p.max_per_product_mw, 0.0)),
        "c7_daily_cycle_mwh": float(cycle),
    }
