"""File names of processed datasets and committed samples, shared by scripts and tests."""

from __future__ import annotations

from pathlib import Path

from nordic_bess.config import Config


def day_ahead_path(cfg: Config) -> Path:
    """Processed day-ahead prices at native resolution (EUR/MWh, UTC)."""
    return cfg.paths.processed / f"day_ahead_{cfg.market.bidding_zone.lower()}.parquet"


def fcr_prices_path(cfg: Config) -> Path:
    """Processed hourly FCR capacity prices, every price series (EUR/MW/h, UTC)."""
    return cfg.paths.processed / f"fcr_prices_{cfg.market.bidding_zone.lower()}.parquet"


def frequency_path(cfg: Config, year: int, month: int, hz: int) -> Path:
    """Processed Fingrid frequency for one month at 10 Hz or 1 Hz (Hz, UTC)."""
    return cfg.paths.processed / f"frequency_{hz}hz_{year}-{month:02d}.parquet"


# Committed extracts used by tests and CI (data/sample/, < 5 MB in total).
SAMPLE_FILES = {
    "day_ahead_week": "day_ahead_se3_week.parquet",
    "day_ahead_15min_day": "day_ahead_se3_15min_day.parquet",
    "fcr_prices_week": "fcr_prices_se3_week.parquet",
    "frequency_1hz_week": "frequency_1hz_week.parquet",
    "frequency_10hz_hour": "frequency_10hz_hour.parquet",
}


def sample_path(cfg: Config, key: str) -> Path:
    return cfg.paths.sample / SAMPLE_FILES[key]
