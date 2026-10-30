"""Download and process all input data into data/processed/ (PLAN M1).

Sources: ENTSO-E day-ahead prices (needs ENTSOE_API_KEY in .env), Svenska kraftnat FCR
capacity prices and Fingrid 10 Hz frequency for the simulation week. Raw downloads are
cached in data/raw/; pass --force to refresh them. --samples rewrites the committed
extracts in data/sample/ used by tests and CI.

Usage: uv run python scripts/fetch_data.py --config configs/base.yaml [--force] [--samples]
"""

from __future__ import annotations

import argparse
import logging
import os

import pandas as pd
from dotenv import find_dotenv, load_dotenv

from nordic_bess.config import Config, load_config
from nordic_bess.data import catalog, entsoe_prices, fingrid, svk_fcr
from nordic_bess.data.validation import validate_time_index

log = logging.getLogger("fetch_data")
SAMPLE_15MIN_DAY = pd.Timestamp("2025-10-15T00:00:00Z")


def build_day_ahead(cfg: Config, force: bool) -> pd.Series:
    load_dotenv(find_dotenv(usecwd=True))
    start = cfg.market.backtest_start - pd.Timedelta(days=cfg.market.lookback_days)
    end = cfg.market.backtest_end
    cache = entsoe_prices.raw_cache_path(cfg.paths.raw, cfg.market.bidding_zone, start, end)
    key = os.environ.get("ENTSOE_API_KEY", "")
    if not key and (force or not cache.exists()):
        raise SystemExit("ENTSOE_API_KEY is not set (see .env.example)")
    prices = entsoe_prices.fetch_day_ahead_prices(
        key, cfg.market.bidding_zone, start, end, cfg.paths.raw, force=force
    )
    for report in entsoe_prices.validate_day_ahead(prices):
        log.info(report.summary())
    prices.to_frame().to_parquet(catalog.day_ahead_path(cfg))
    return prices


def build_fcr_prices(cfg: Config, force: bool) -> pd.DataFrame:
    csv_path = svk_fcr.download_svk_fcr(cfg.paths.raw, force=force)
    long = svk_fcr.parse_svk_fcr(csv_path, cfg.market.bidding_zone)
    table = svk_fcr.all_price_series(long)
    report = validate_time_index(table.index, "1h", "FCR prices (all history)")
    log.info(report.summary())
    table.to_parquet(catalog.fcr_prices_path(cfg))
    return table


def build_frequency(cfg: Config, force: bool) -> dict[tuple[int, int], pd.Series]:
    out = {}
    for year, month in fingrid.months_covering(cfg.simulation.week_start, cfg.simulation.week_end):
        archive = fingrid.download_month(cfg.paths.raw, year, month, force=force)
        folder = fingrid.extract_month(archive, force=force)
        f10, report, n_dup = fingrid.load_month(folder)
        log.info("%s; %d duplicate timestamps dropped", report.summary(), n_dup)
        f1 = fingrid.to_1hz(f10)
        log.info("1 Hz %d-%02d: %d seconds, %d empty", year, month, len(f1), f1.isna().sum())
        f10.to_frame().to_parquet(catalog.frequency_path(cfg, year, month, 10))
        f1.to_frame().to_parquet(catalog.frequency_path(cfg, year, month, 1))
        out[(year, month)] = f1
    return out


def write_samples(cfg: Config, prices: pd.Series, fcr: pd.DataFrame) -> None:
    """Write the small committed extracts used by tests and CI."""
    cfg.paths.sample.mkdir(parents=True, exist_ok=True)
    w0, w1 = cfg.simulation.week_start, cfg.simulation.week_end
    prices[(prices.index >= w0) & (prices.index < w1)].to_frame().to_parquet(
        catalog.sample_path(cfg, "day_ahead_week")
    )
    d1 = SAMPLE_15MIN_DAY + pd.Timedelta(days=1)
    prices[(prices.index >= SAMPLE_15MIN_DAY) & (prices.index < d1)].to_frame().to_parquet(
        catalog.sample_path(cfg, "day_ahead_15min_day")
    )
    fcr[(fcr.index >= w0) & (fcr.index < w1)].to_parquet(
        catalog.sample_path(cfg, "fcr_prices_week")
    )

    year, month = fingrid.months_covering(w0, w1)[0]
    f1 = pd.read_parquet(catalog.frequency_path(cfg, year, month, 1))[fingrid.FREQ_COLUMN]
    week = f1[(f1.index >= w0) & (f1.index < w1)].astype("float32")
    week.to_frame().to_parquet(
        catalog.sample_path(cfg, "frequency_1hz_week"),
        compression="zstd",
        use_byte_stream_split=[fingrid.FREQ_COLUMN],
    )
    f10 = pd.read_parquet(catalog.frequency_path(cfg, year, month, 10))[fingrid.FREQ_COLUMN]
    hour = f10[(f10.index >= w0) & (f10.index < w0 + pd.Timedelta(hours=1))]
    hour.to_frame().to_parquet(catalog.sample_path(cfg, "frequency_10hz_hour"), compression="zstd")
    total = sum(p.stat().st_size for p in cfg.paths.sample.glob("*.parquet"))
    log.info("samples written to %s: %.2f MB in total", cfg.paths.sample, total / 1e6)


def print_headline(cfg: Config, prices: pd.Series, fcr: pd.DataFrame) -> None:
    """M1 acceptance: mean DA price and mean FCR price per product over the backtest window."""
    s, e = cfg.market.backtest_start, cfg.market.backtest_end
    hourly = entsoe_prices.to_hourly(prices[(prices.index >= s) & (prices.index < e)])
    print(
        f"Mean day-ahead price {cfg.market.bidding_zone} {s:%Y-%m-%d} -> {e:%Y-%m-%d}: "
        f"{hourly.mean():.2f} EUR/MWh (hourly mean of native prices, {len(hourly)} h)"
    )
    window = fcr[(fcr.index >= s) & (fcr.index < e)]
    for series in svk_fcr.PRICE_SERIES:
        table = svk_fcr.select_series(window, series)
        means = ", ".join(
            f"{c.split('_eur')[0].removeprefix('price_')}={v:.2f}" for c, v in table.mean().items()
        )
        print(f"Mean FCR capacity price [{series}] (EUR/MW/h): {means}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--force", action="store_true", help="re-download raw files")
    parser.add_argument("--samples", action="store_true", help="rewrite data/sample/ extracts")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    cfg.paths.processed.mkdir(parents=True, exist_ok=True)
    prices = build_day_ahead(cfg, args.force)
    fcr = build_fcr_prices(cfg, args.force)
    build_frequency(cfg, args.force)
    if args.samples:
        write_samples(cfg, prices, fcr)
    print_headline(cfg, prices, fcr)


if __name__ == "__main__":
    main()
