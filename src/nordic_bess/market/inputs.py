"""Price inputs for the backtest, aligned on UTC days (PLAN M2).

Day-ahead prices are taken at the model resolution: the hourly mean of the native
prices for the hourly model, or 15-minute prices for the M2b model (before the
2025-10-01 switch the hourly price applies to its four quarters). FCR prices are hourly
EUR/MW/h for the configured series.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nordic_bess.config import Config
from nordic_bess.data import catalog
from nordic_bess.data.entsoe_prices import load_day_ahead, to_hourly
from nordic_bess.data.svk_fcr import PRICE_COLUMNS, load_fcr_prices
from nordic_bess.data.validation import DataValidationError
from nordic_bess.market.milp import HOURS_PER_DAY, DayPrices


@dataclass(frozen=True)
class MarketPrices:
    """Aligned prices: ``da`` per model period [EUR/MWh], ``fcr`` per hour [EUR/MW/h]."""

    da: pd.Series
    fcr: pd.DataFrame
    periods_per_hour: int
    n_fcr_hours_without_auction: int

    @property
    def days(self) -> pd.DatetimeIndex:
        """UTC midnights of the days covered."""
        return pd.date_range(self.fcr.index[0], self.fcr.index[-1], freq="D").normalize()

    def day(self, day: pd.Timestamp) -> DayPrices:
        """Prices of one UTC day as arrays for :class:`~nordic_bess.market.milp.DailyMilp`."""
        nxt = day + pd.Timedelta(days=1)
        da = self.da[(self.da.index >= day) & (self.da.index < nxt)].to_numpy()
        fcr = self.fcr[(self.fcr.index >= day) & (self.fcr.index < nxt)]
        if len(da) != HOURS_PER_DAY * self.periods_per_hour or len(fcr) != HOURS_PER_DAY:
            raise DataValidationError(f"incomplete price data on {day:%Y-%m-%d}")
        cols = list(PRICE_COLUMNS.values())
        return DayPrices(
            da_eur_per_mwh=da,
            fcr_n_eur_per_mw_h=fcr[cols[0]].to_numpy(),
            fcr_dup_eur_per_mw_h=fcr[cols[1]].to_numpy(),
            fcr_ddown_eur_per_mw_h=fcr[cols[2]].to_numpy(),
        )


def prepare_prices(
    da_native: pd.Series,
    fcr_hourly: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    periods_per_hour: int,
    series: str,
) -> MarketPrices:
    """Align native day-ahead and hourly FCR prices on ``[start, end)`` (whole UTC days).

    For a single auction round, an hour in which that round was not held has no sellable
    capacity and gets price 0 (counted in ``n_fcr_hours_without_auction``). For the
    ``total`` series a missing hour is a data error.
    """
    if start != start.normalize() or end != end.normalize():
        raise ValueError("backtest window must start and end at UTC midnight")
    if periods_per_hour not in (1, 4):
        raise ValueError("periods_per_hour must be 1 (hourly) or 4 (15 minutes)")

    window = da_native[(da_native.index >= start) & (da_native.index < end)]
    if periods_per_hour == 1:
        da = to_hourly(window)
        grid = pd.date_range(start, end, freq="1h", inclusive="left")
    else:
        grid = pd.date_range(start, end, freq="15min", inclusive="left")
        da = window.reindex(grid, method="ffill")
    da = da.reindex(grid)
    if da.isna().any():
        raise DataValidationError(f"day-ahead prices missing for {int(da.isna().sum())} periods")

    hours = pd.date_range(start, end, freq="1h", inclusive="left")
    fcr = fcr_hourly.reindex(hours)
    missing = int(fcr.isna().any(axis=1).sum())
    if missing and series == "total":
        raise DataValidationError(f"FCR 'total' prices missing for {missing} hours")
    fcr = fcr.fillna(0.0)
    da.index.name = fcr.index.name = "time_utc"
    return MarketPrices(
        da=da.astype(np.float64),
        fcr=fcr.astype(np.float64),
        periods_per_hour=periods_per_hour,
        n_fcr_hours_without_auction=missing,
    )


def load_backtest_prices(
    cfg: Config,
    periods_per_hour: int = 1,
    series: str | None = None,
    start: pd.Timestamp | None = None,
) -> MarketPrices:
    """Read processed prices and align them on the backtest window.

    ``start`` overrides the window start, e.g. one week earlier for the naive forecast
    (it must lie within the ``lookback_days`` fetched by ``fetch_data.py``).
    """
    series = series or cfg.market.fcr_price_series
    da = load_day_ahead(catalog.day_ahead_path(cfg))
    fcr = load_fcr_prices(catalog.fcr_prices_path(cfg), series)
    begin = cfg.market.backtest_start if start is None else start
    return prepare_prices(da, fcr, begin, cfg.market.backtest_end, periods_per_hour, series)
