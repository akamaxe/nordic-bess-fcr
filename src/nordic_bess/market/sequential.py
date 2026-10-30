"""Sequential bidding with naive forecasts.

FCR capacity is procured before the day-ahead auction (D-2 and D-1 rounds), so the
capacity decision has to rely on forecasts. Two sequential variants are compared with
the perfect-foresight backtest:

- ``fcr_forecast``: FCR capacities are chosen with forecast prices; the day-ahead
  schedule is then optimised with the actual day-ahead prices and the capacities fixed
  (isolates the value of knowing FCR prices in advance);
- ``all_forecast``: both decisions use forecast prices and are settled at actual prices
  (the battery commits its whole day before seeing any price).

The forecast is "same hour last week" for both day-ahead and FCR prices. As a price
taker, every capacity offered is accepted and paid the clearing price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nordic_bess.config import SolverConfig
from nordic_bess.market.inputs import MarketPrices
from nordic_bess.market.milp import HOURS_PER_DAY, DailyMilp, MilpParams, constraint_violations
from nordic_bess.market.strategies import STRATEGIES, BacktestResult

FORECAST_LAG = pd.Timedelta(days=7)
PRICE_COLUMNS_SCHEDULE = (
    "price_da_eur_per_mwh",
    "price_fcr_n_eur_per_mw_h",
    "price_fcr_dup_eur_per_mw_h",
    "price_fcr_ddown_eur_per_mw_h",
)


def naive_forecast(actual: MarketPrices, start: pd.Timestamp, end: pd.Timestamp) -> MarketPrices:
    """Same-hour-last-week forecast of every price on ``[start, end)``.

    ``actual`` must cover ``[start - 7 days, end)``.
    """
    if actual.fcr.index[0] > start - FORECAST_LAG:
        raise ValueError("actual prices must start at least 7 days before the forecast window")

    def shift(obj):
        moved = obj.copy()
        moved.index = moved.index + FORECAST_LAG
        return moved[(moved.index >= start) & (moved.index < end)]

    return MarketPrices(
        da=shift(actual.da),
        fcr=shift(actual.fcr),
        periods_per_hour=actual.periods_per_hour,
        n_fcr_hours_without_auction=0,
    )


def _hourly_capacity(periods: pd.DataFrame, pph: int) -> np.ndarray:
    cols = ["c_n_mw", "c_dup_mw", "c_ddown_mw"]
    return periods[cols].to_numpy()[::pph][:HOURS_PER_DAY]


def run_sequential(
    actual: MarketPrices,
    forecast: MarketPrices,
    params: MilpParams,
    solver: SolverConfig,
    variant: str,
    tol: float = 1e-6,
) -> BacktestResult:
    """Run the S3 strategy day by day with forecast-based decisions (see module docstring).

    The returned schedule carries the *actual* prices, so the KPIs are settled revenues.
    """
    if variant not in ("fcr_forecast", "all_forecast"):
        raise ValueError("variant must be 'fcr_forecast' or 'all_forecast'")
    strategy = STRATEGIES["S3"]
    milp = DailyMilp(params, strategy, solver, forecast.periods_per_hour)
    frames, solve_time, worst = [], 0.0, 0.0
    for day in forecast.days:
        first = milp.solve(forecast.day(day))
        solve_time += first.solve_time_s
        actual_day = actual.day(day)
        if variant == "fcr_forecast":
            caps = _hourly_capacity(first.periods, milp.pph)
            sol = milp.solve(actual_day, fixed_capacity=caps)
            solve_time += sol.solve_time_s
            periods = sol.periods
        else:
            periods = first.periods.copy()
            hours = np.arange(len(periods)) // milp.pph
            periods["price_da_eur_per_mwh"] = actual_day.da_eur_per_mwh
            periods["price_fcr_n_eur_per_mw_h"] = actual_day.fcr_n_eur_per_mw_h[hours]
            periods["price_fcr_dup_eur_per_mw_h"] = actual_day.fcr_dup_eur_per_mw_h[hours]
            periods["price_fcr_ddown_eur_per_mw_h"] = actual_day.fcr_ddown_eur_per_mw_h[hours]
        worst = max(worst, max(constraint_violations(periods, params, milp.dt_h).values()))
        if worst > tol:
            raise AssertionError(f"{variant} {day:%Y-%m-%d}: constraint violated by {worst:.3g}")
        idx = pd.date_range(day, periods=len(periods), freq=pd.Timedelta(hours=milp.dt_h))
        frames.append(periods.set_index(idx.rename("time_utc")))
    return BacktestResult(
        strategy=strategy,
        schedule=pd.concat(frames),
        dt_h=milp.dt_h,
        solve_time_s=solve_time,
        max_violation=worst,
    )
