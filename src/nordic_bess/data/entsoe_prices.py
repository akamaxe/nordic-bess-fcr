"""SE3 day-ahead prices from the ENTSO-E Transparency Platform (via ``entsoe-py``).

ENTSO-E returns Europe/Stockholm local time and includes the end timestamp of the
query; :func:`fetch_day_ahead_prices` converts to UTC and keeps ``[start, end)``.
The SDAC market time unit changed from 60 to 15 minutes from delivery day 2025-10-01
(2025-09-30 22:00 UTC); the native resolution is stored and :func:`to_hourly`
resamples explicitly where a model needs hourly prices.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nordic_bess.data.validation import DataValidationError, GapReport, validate_time_index

PRICE_COLUMN = "price_eur_per_mwh"
#: First 15-minute market time unit of the SDAC (delivery day 2025-10-01, CEST).
MTU_15MIN_START_UTC = pd.Timestamp("2025-09-30T22:00:00Z")
ENTSOE_ZONE_CODES = {"SE1": "SE_1", "SE2": "SE_2", "SE3": "SE_3", "SE4": "SE_4"}


def raw_cache_path(raw_dir: Path, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    """Cache file for one ENTSO-E query (raw local-time response)."""
    fmt = "%Y%m%dT%H%MZ"
    name = f"day_ahead_{ENTSOE_ZONE_CODES[zone]}_{start:{fmt}}_{end:{fmt}}.parquet"
    return raw_dir / "entsoe" / name


def fetch_day_ahead_prices(
    api_key: str,
    zone: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    raw_dir: Path,
    force: bool = False,
) -> pd.Series:
    """Download (or read from cache) day-ahead prices in EUR/MWh for ``[start, end)`` UTC.

    Args:
        api_key: ENTSO-E Transparency Platform token (never logged).
        zone: Bidding zone, e.g. ``"SE3"``.
        start: Inclusive start, tz-aware.
        end: Exclusive end, tz-aware.
        raw_dir: ``data/raw``; the response is cached under ``raw_dir/entsoe``.
        force: Re-download even if the cache file exists.

    Returns:
        Series named ``price_eur_per_mwh`` on a tz-aware UTC index at native resolution.
    """
    path = raw_cache_path(raw_dir, zone, start, end)
    if force or not path.exists():
        from entsoe import EntsoePandasClient  # imported lazily: network-only dependency

        client = EntsoePandasClient(api_key=api_key)
        local = client.query_day_ahead_prices(
            ENTSOE_ZONE_CODES[zone],
            start=start.tz_convert("Europe/Stockholm"),
            end=end.tz_convert("Europe/Stockholm"),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        local.rename(PRICE_COLUMN).to_frame().to_parquet(path)
    raw = pd.read_parquet(path)[PRICE_COLUMN]
    return clean_day_ahead(raw, start, end)


def clean_day_ahead(raw: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Convert a raw ENTSO-E response to UTC, keep ``[start, end)`` and validate it."""
    if raw.index.tz is None:
        raise DataValidationError("ENTSO-E prices: expected a tz-aware index")
    s = raw.tz_convert("UTC").astype("float64")
    s = s[(s.index >= start) & (s.index < end)]
    s.index.name = "time_utc"
    s.name = PRICE_COLUMN
    validate_day_ahead(s)
    return s


def validate_day_ahead(prices: pd.Series) -> tuple[GapReport, ...]:
    """Validate a day-ahead series: 60 min before the 15-min MTU switch, 15 min after.

    Raises:
        DataValidationError: On NaN prices or any index violation.
    """
    if prices.isna().any():
        raise DataValidationError(f"day-ahead prices: {int(prices.isna().sum())} NaN values")
    reports = []
    hourly = prices[prices.index < MTU_15MIN_START_UTC]
    quarter = prices[prices.index >= MTU_15MIN_START_UTC]
    if len(hourly):
        reports.append(validate_time_index(hourly.index, "1h", "day-ahead (60 min MTU)"))
    if len(quarter):
        reports.append(validate_time_index(quarter.index, "15min", "day-ahead (15 min MTU)"))
    return tuple(reports)


def to_hourly(prices: pd.Series) -> pd.Series:
    """Hourly mean of a day-ahead series in EUR/MWh (identity on hourly data).

    The hourly value is the arithmetic mean of the 15-minute prices inside the hour,
    which equals the volume-neutral average a 1-hour schedule would pay or earn.
    """
    hourly = prices.resample("1h").mean()
    if hourly.isna().any():
        raise DataValidationError("to_hourly: empty hours in the input (gaps in the data)")
    return hourly.rename(prices.name)


def load_day_ahead(path: Path) -> pd.Series:
    """Read processed day-ahead prices (``time_utc`` index, EUR/MWh) and validate them."""
    s = pd.read_parquet(path)[PRICE_COLUMN]
    validate_day_ahead(s)
    return s
