"""Scenario-based two-stage stochastic bidding (PLAN M2b, optional item).

First stage: hourly FCR capacities ``c_N``, ``c_Dup``, ``c_Ddown``, common to all
scenarios (they are committed in the FCR auctions before prices are known). Second
stage: a day-ahead schedule per scenario. The objective is the expected revenue over
equally likely scenarios; each scenario satisfies constraints 1-7 of the daily MILP
(``nordic_bess.market.milp``). Scenarios are the prices of the same hours in the previous
``n_weeks`` weeks.

The capacities are then evaluated like the ``fcr_forecast`` sequential variant: fixed,
with the day-ahead schedule re-optimised on actual prices and settled at actual prices.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.contrib.appsi.base import TerminationCondition
from pyomo.contrib.appsi.solvers import Highs

from nordic_bess.config import SolverConfig
from nordic_bess.market.inputs import MarketPrices
from nordic_bess.market.milp import (
    HOURS_PER_DAY,
    DailyMilp,
    DayPrices,
    MilpParams,
    constraint_violations,
)
from nordic_bess.market.strategies import STRATEGIES, BacktestResult


class StochasticDailyMilp:
    """Two-stage stochastic version of the S3 daily MILP with ``n_scenarios`` scenarios."""

    def __init__(self, params: MilpParams, solver: SolverConfig, n_scenarios: int) -> None:
        self.params = params
        self.n_scenarios = int(n_scenarios)
        self.model = self._build()
        self.solver = Highs()
        self.solver.config.mip_gap = solver.mip_rel_gap
        self.solver.config.time_limit = solver.time_limit_s

    def _build(self) -> pyo.ConcreteModel:
        p = self.params
        m = pyo.ConcreteModel(name="stochastic_daily_milp")
        m.S = pyo.RangeSet(0, self.n_scenarios - 1)
        m.T = pyo.RangeSet(0, HOURS_PER_DAY - 1)
        m.K = pyo.RangeSet(0, HOURS_PER_DAY)
        m.lam = pyo.Param(m.S, m.T, mutable=True, initialize=0.0)
        m.pi_n = pyo.Param(m.S, m.T, mutable=True, initialize=0.0)
        m.pi_dup = pyo.Param(m.S, m.T, mutable=True, initialize=0.0)
        m.pi_ddown = pyo.Param(m.S, m.T, mutable=True, initialize=0.0)
        cap = (0.0, p.max_per_product_mw)
        m.c_n = pyo.Var(m.T, bounds=cap)  # first stage
        m.c_dup = pyo.Var(m.T, bounds=cap)
        m.c_ddown = pyo.Var(m.T, bounds=cap)
        m.p_c = pyo.Var(m.S, m.T, bounds=(0.0, p.p_max_mw))  # second stage
        m.p_d = pyo.Var(m.S, m.T, bounds=(0.0, p.p_max_mw))
        m.u = pyo.Var(m.S, m.T, domain=pyo.Binary)
        m.e = pyo.Var(m.S, m.K, bounds=(p.e_min_mwh, p.e_max_mwh))

        m.c1d = pyo.Constraint(m.S, m.T, rule=lambda m, s, t: m.p_d[s, t] <= p.p_max_mw * m.u[s, t])
        m.c1c = pyo.Constraint(
            m.S, m.T, rule=lambda m, s, t: m.p_c[s, t] <= p.p_max_mw * (1 - m.u[s, t])
        )
        m.c2 = pyo.Constraint(
            m.S,
            m.T,
            rule=lambda m, s, t: (
                m.e[s, t + 1] == m.e[s, t] + p.eta_c * m.p_c[s, t] - m.p_d[s, t] / p.eta_d
            ),
        )
        m.c3 = pyo.Constraint(
            m.S,
            m.T,
            rule=lambda m, s, t: (
                (m.p_d[s, t] - m.p_c[s, t])
                + p.power_factor_n * m.c_n[t]
                + m.c_dup[t]
                + p.power_factor_d_opposite * m.c_ddown[t]
                <= p.p_max_mw
            ),
        )
        m.c4 = pyo.Constraint(
            m.S,
            m.T,
            rule=lambda m, s, t: (
                (m.p_d[s, t] - m.p_c[s, t])
                - p.power_factor_n * m.c_n[t]
                - p.power_factor_d_opposite * m.c_dup[t]
                - m.c_ddown[t]
                >= -p.p_max_mw
            ),
        )
        ends = pyo.Set(initialize=[0, 1])
        m.c5 = pyo.Constraint(
            m.S,
            m.T,
            ends,
            rule=lambda m, s, t, j: (
                p.eta_d * (m.e[s, t + j] - p.e_min_mwh)
                >= p.energy_hours_n * m.c_n[t] + p.energy_hours_d * m.c_dup[t]
            ),
        )
        m.c6 = pyo.Constraint(
            m.S,
            m.T,
            ends,
            rule=lambda m, s, t, j: (
                (p.e_max_mwh - m.e[s, t + j]) / p.eta_c
                >= p.energy_hours_n * m.c_n[t] + p.energy_hours_d * m.c_ddown[t]
            ),
        )
        m.c7a = pyo.Constraint(m.S, rule=lambda m, s: m.e[s, 0] == p.e0_mwh)
        m.c7b = pyo.Constraint(m.S, rule=lambda m, s: m.e[s, HOURS_PER_DAY] == p.e0_mwh)
        weight = 1.0 / self.n_scenarios
        m.obj = pyo.Objective(
            expr=weight
            * sum(
                m.lam[s, t] * (m.p_d[s, t] - m.p_c[s, t])
                - p.c_deg_eur_per_mwh * m.p_d[s, t]
                + m.pi_n[s, t] * m.c_n[t]
                + m.pi_dup[s, t] * m.c_dup[t]
                + m.pi_ddown[s, t] * m.c_ddown[t]
                for s in m.S
                for t in m.T
            ),
            sense=pyo.maximize,
        )
        return m

    def solve(self, scenarios: list[DayPrices]) -> tuple[np.ndarray, float, float]:
        """Optimal first-stage capacities ``(24, 3)`` [MW], expected revenue and solve time."""
        if len(scenarios) != self.n_scenarios:
            raise ValueError(f"expected {self.n_scenarios} scenarios")
        m = self.model
        for s, sc in enumerate(scenarios):
            for t in m.T:
                m.lam[s, t].set_value(float(sc.da_eur_per_mwh[t]))
                m.pi_n[s, t].set_value(float(sc.fcr_n_eur_per_mw_h[t]))
                m.pi_dup[s, t].set_value(float(sc.fcr_dup_eur_per_mw_h[t]))
                m.pi_ddown[s, t].set_value(float(sc.fcr_ddown_eur_per_mw_h[t]))
        t0 = time.perf_counter()
        res = self.solver.solve(m)
        elapsed = time.perf_counter() - t0
        if res.termination_condition != TerminationCondition.optimal:
            raise RuntimeError(f"stochastic MILP: solver returned {res.termination_condition}")
        caps = np.array([[pyo.value(v[t]) for v in (m.c_n, m.c_dup, m.c_ddown)] for t in m.T]).clip(
            min=0.0
        )
        return caps, float(pyo.value(m.obj)), elapsed


def run_stochastic(
    actual: MarketPrices,
    history: MarketPrices,
    params: MilpParams,
    solver: SolverConfig,
    n_weeks: int,
    tol: float = 1e-6,
) -> BacktestResult:
    """Choose FCR capacities on past-week scenarios, then re-optimise the day-ahead
    schedule on actual prices with the capacities fixed (hourly model only).

    ``history`` must start at least ``n_weeks`` weeks before ``actual``.
    """
    if actual.periods_per_hour != 1:
        raise ValueError("the stochastic model is hourly")
    if history.fcr.index[0] > actual.fcr.index[0] - pd.Timedelta(weeks=n_weeks):
        raise ValueError(f"history must cover {n_weeks} weeks before the backtest")
    stochastic = StochasticDailyMilp(params, solver, n_weeks)
    second = DailyMilp(params, STRATEGIES["S3"], solver)
    frames, solve_time, worst = [], 0.0, 0.0
    for day in actual.days:
        scenarios = [history.day(day - pd.Timedelta(weeks=w)) for w in range(1, n_weeks + 1)]
        caps, _, t1 = stochastic.solve(scenarios)
        sol = second.solve(actual.day(day), fixed_capacity=caps)
        solve_time += t1 + sol.solve_time_s
        worst = max(worst, max(constraint_violations(sol.periods, params, sol.dt_h).values()))
        if worst > tol:
            raise AssertionError(f"stochastic {day:%Y-%m-%d}: constraint violated by {worst:.3g}")
        idx = pd.date_range(day, periods=len(sol.periods), freq="1h", name="time_utc")
        frames.append(sol.periods.set_index(idx))
    return BacktestResult(
        strategy=STRATEGIES["S3"],
        schedule=pd.concat(frames),
        dt_h=1.0,
        solve_time_s=solve_time,
        max_violation=worst,
    )
