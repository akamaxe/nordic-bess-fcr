"""Loader tests on synthetic inputs and on the committed samples (no network)."""

import numpy as np
import pandas as pd
import pytest

from nordic_bess.data import catalog, entsoe_prices, fingrid, svk_fcr
from nordic_bess.data.validation import DataValidationError, validate_time_index

# --- ENTSO-E -----------------------------------------------------------------------------


def _raw_entsoe(start_utc: str, end_utc: str) -> pd.Series:
    """Mimic entsoe-py: local time, hourly then 15 min, end timestamp included."""
    hourly = pd.date_range(start_utc, "2025-09-30T22:00Z", freq="1h", inclusive="left")
    quarter = pd.date_range("2025-09-30T22:00Z", end_utc, freq="15min")  # inclusive end
    idx = hourly.append(quarter).tz_convert("Europe/Stockholm")
    return pd.Series(np.arange(len(idx), dtype=float), index=idx)


def test_clean_day_ahead_drops_inclusive_end_and_converts_to_utc():
    start, end = pd.Timestamp("2025-09-30T20:00Z"), pd.Timestamp("2025-10-01T00:00Z")
    s = entsoe_prices.clean_day_ahead(_raw_entsoe(str(start), str(end)), start, end)
    assert str(s.index.tz) == "UTC"
    assert s.index[-1] < end
    assert len(s) == 2 + 8  # two hourly values, then 2 h at 15 min
    assert s.name == "price_eur_per_mwh"


def test_validate_day_ahead_rejects_15min_before_switch():
    idx = pd.date_range("2025-09-01T00:00Z", periods=8, freq="15min")
    with pytest.raises(DataValidationError):
        entsoe_prices.validate_day_ahead(pd.Series(1.0, index=idx))


def test_to_hourly_averages_quarters(config):
    day = entsoe_prices.load_day_ahead(catalog.sample_path(config, "day_ahead_15min_day"))
    assert len(day) == 96
    hourly = entsoe_prices.to_hourly(day)
    assert len(hourly) == 24
    assert hourly.iloc[0] == pytest.approx(day.iloc[:4].mean())
    assert hourly.mean() == pytest.approx(day.mean())


def test_to_hourly_is_identity_on_hourly_sample(config):
    week = entsoe_prices.load_day_ahead(catalog.sample_path(config, "day_ahead_week"))
    assert len(week) == 168
    pd.testing.assert_series_equal(entsoe_prices.to_hourly(week), week, check_freq=False)


# --- Svk FCR -----------------------------------------------------------------------------

SVK_HEADER = (
    "_id,start_time_sweden,start_time_utc,bidding_zone,reserve_product,reserve_direction,"
    "auction_round,price,price_unit,volume,volume_unit,soda_hashbyte,soda_identity\n"
)


def _svk_csv(tmp_path, rows):
    lines = [
        f"{i},x,{t},{z},{p},{d},{r},{price},EUR-MW,{vol},MW,h,{i}"
        for i, (t, z, p, d, r, price, vol) in enumerate(rows)
    ]
    path = tmp_path / "svk.csv"
    path.write_text(SVK_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_total_series_is_volume_weighted(tmp_path):
    t = "2025-03-03T05:00:00"
    path = _svk_csv(
        tmp_path,
        [
            (t, "SE3", "FCRN", "symmetric", "fcrAuction1", 20.0, 30.0),
            (t, "SE3", "FCRN", "symmetric", "fcrAuction2", 40.0, 10.0),
            (t, "SE3", "FCRD", "up", "fcrAuction1", 5.0, 100.0),
            (t, "SE3", "FCRD", "down", "fcrAuction2", 7.0, 50.0),
            (t, "SE1", "FCRN", "symmetric", "fcrAuction1", 99.0, 1.0),
        ],
    )
    long = svk_fcr.parse_svk_fcr(path, "SE3")
    total = svk_fcr.fcr_price_table(long, "total").iloc[0]
    assert total["price_fcr_n_eur_per_mw_h"] == pytest.approx((20 * 30 + 40 * 10) / 40)
    assert total["price_fcr_dup_eur_per_mw_h"] == pytest.approx(5.0)
    r2 = svk_fcr.fcr_price_table(long, "fcrAuction2").iloc[0]
    assert r2["price_fcr_n_eur_per_mw_h"] == 40.0
    assert np.isnan(r2["price_fcr_dup_eur_per_mw_h"])
    assert str(total.name.tz) == "UTC"


def test_unknown_product_fails_loudly(tmp_path):
    path = _svk_csv(tmp_path, [("2025-03-03T05:00:00", "SE3", "FFR", "up", "fcrAuction1", 1, 1)])
    with pytest.raises(DataValidationError, match="unknown product"):
        svk_fcr.parse_svk_fcr(path, "SE3")


def test_fcr_sample_has_all_series(config):
    table = pd.read_parquet(catalog.sample_path(config, "fcr_prices_week"))
    validate_time_index(table.index, "1h", "sample")
    assert len(table) == 168
    for series in svk_fcr.PRICE_SERIES:
        sel = svk_fcr.select_series(table, series)
        assert list(sel.columns) == list(svk_fcr.PRICE_COLUMNS.values())
        assert (sel.dropna() > 0).all().all()
        if series != "fcrAuction2":  # round 2 is not held every hour (DATA.md)
            assert sel.notna().all().all()


# --- Fingrid -----------------------------------------------------------------------------


def _fingrid_csv(tmp_path, name, local_times, values):
    path = tmp_path / name
    body = "\n".join(f"{t},{v}" for t, v in zip(local_times, values, strict=True))
    path.write_text("Time,Value\n" + body + "\n", encoding="utf-8")
    return path


def test_dst_start_day_converts_without_overlap(tmp_path):
    times = ["2025-03-30 02:59:59.900", "2025-03-30 04:00:00.000"]  # 03:xx does not exist
    path = _fingrid_csv(tmp_path, "Taajuusdata2025-03-30.csv", times, [50.0, 49.9])
    s = fingrid.read_day_csv(path)
    assert list(s.index) == [
        pd.Timestamp("2025-03-30T00:59:59.900Z"),
        pd.Timestamp("2025-03-30T01:00:00Z"),
    ]


def test_load_month_drops_duplicates(tmp_path):
    folder = tmp_path / "2025-03"
    folder.mkdir()
    t = ["2025-03-03 00:00:00.000", "2025-03-03 00:00:00.100", "2025-03-03 00:00:00.100"]
    _fingrid_csv(folder, "Taajuusdata2025-03-03.csv", t, [50.0, 50.01, 50.02])
    s, report, n_dup = fingrid.load_month(folder)
    assert n_dup == 1
    assert s.iloc[-1] == 50.01
    assert report.n_points == 2


def test_to_1hz_and_gap_filling():
    idx = pd.date_range("2025-03-03T00:00Z", periods=50, freq="100ms")
    f10 = pd.Series(50.0 + np.arange(50) * 1e-3, index=idx).drop(idx[20:30])  # second 2
    f1 = fingrid.to_1hz(f10)
    assert len(f1) == 5
    assert np.isnan(f1.iloc[2])
    assert f1.iloc[0] == pytest.approx(f10.iloc[:10].mean())
    filled, n = fingrid.fill_short_gaps(f1, max_gap_s=1)
    assert n == 1
    assert filled.iloc[2] == pytest.approx((f1.iloc[1] + f1.iloc[3]) / 2)
    with pytest.raises(DataValidationError):
        fingrid.fill_short_gaps(f1, max_gap_s=0)


def test_months_covering_uses_finnish_months():
    # 2025-03-31T22:00Z is already April in Helsinki (UTC+3).
    months = fingrid.months_covering(
        pd.Timestamp("2025-03-03T00:00Z"), pd.Timestamp("2025-03-31T22:00:01Z")
    )
    assert months == [(2025, 3), (2025, 4)]


def test_frequency_samples(config):
    f1 = pd.read_parquet(catalog.sample_path(config, "frequency_1hz_week"))["f_hz"]
    report = validate_time_index(f1.index, "1s", "sample 1 Hz")
    assert report.n_points == 7 * 86400
    assert f1.between(49.7, 50.3).sum() >= 0.999 * len(f1)
    f10 = pd.read_parquet(catalog.sample_path(config, "frequency_10hz_hour"))["f_hz"]
    validate_time_index(f10.index, "100ms", "sample 10 Hz")


def test_samples_stay_small(config):
    total = sum(p.stat().st_size for p in config.paths.sample.glob("*"))
    assert total < 5e6
