"""Bidding strategies S0-S3 and the day-by-day backtest loop (PLAN M2).

All strategies use the same MILP; a strategy only switches revenue streams off by
fixing their variables to zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from nordic_bess.config import SolverConfig
from nordic_bess.market.inputs import MarketPrices
from nordic_bess.market.milp import DailyMilp, MilpParams, Strategy, constraint_violations

STRATEGIES: dict[str, Strategy] = {
    "S0": Strategy("S0", "Day-ahead arbitrage only", True, False, False, False),
    "S1": Strategy("S1", "FCR-N only", False, True, False, False),
    "S2": Strategy("S2", "FCR-D up and down only", False, False, True, True),
    "S3": Strategy("S3", "FCR-N, FCR-D and day-ahead co-optimised", True, True, True, True),
}


@dataclass(frozen=True)
class BacktestResult:
    """Schedule of a whole backtest (one row per model period, UTC index)."""

    strategy: Strategy
    schedule: pd.DataFrame
    dt_h: float
    solve_time_s: float
    max_violation: float


def run_backtest(
    prices: MarketPrices,
    params: MilpParams,
    strategy: Strategy,
    solver: SolverConfig,
    tol: float = 1e-6,
) -> BacktestResult:
    """Solve every UTC day of ``prices`` independently with perfect foresight.

    Each day starts and ends at the target energy (constraint 7), so days are
    independent. Constraints 1-7 are re-checked on every solution.

    Raises:
        AssertionError: If any solved day violates a constraint by more than ``tol``.
    """
    milp = DailyMilp(params, strategy, solver, prices.periods_per_hour)
    frames, solve_time, worst = [], 0.0, 0.0
    for day in prices.days:
        sol = milp.solve(prices.day(day))
        viol = constraint_violations(sol.periods, params, sol.dt_h)
        name, value = max(viol.items(), key=lambda kv: kv[1])
        if value > tol:
            raise AssertionError(f"{strategy.name} {day:%Y-%m-%d}: {name} violated by {value:.3g}")
        worst = max(worst, value)
        solve_time += sol.solve_time_s
        idx = pd.date_range(day, periods=len(sol.periods), freq=pd.Timedelta(hours=sol.dt_h))
        frames.append(sol.periods.set_index(idx.rename("time_utc")))
    return BacktestResult(
        strategy=strategy,
        schedule=pd.concat(frames),
        dt_h=milp.dt_h,
        solve_time_s=solve_time,
        max_violation=worst,
    )
